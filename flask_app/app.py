"""Main Flask and Socket.IO application."""
import os
import json
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from flask import Flask, render_template, request, jsonify, session
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv

load_dotenv()

from flask_app.database import db
db.init_db()

from flask_app.utils.pdf_parser import extract_text_from_pdf
from flask_app.utils.jobs_fetcher import ensure_jobs_available
from flask_app.utils.embedding_service import generate_embedding, cosine_similarity, valid_embedding, EMBEDDING_MODEL
from flask_app.agents.cv_analyzer import analyze_cv
from flask_app.agents.match_scorer import score_match
from flask_app.agents.chat_orchestrator import route_message
from flask_app.agents.chat_query import answer_question
from flask_app.agents.cover_letter import generate_cover_letter
from flask_app.agents.cv_improvement import suggest_cv_improvements

app = Flask(__name__,
            template_folder='templates',
            static_folder='static')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24).hex())
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

socketio = SocketIO(app, async_mode='threading')


def get_device_id():
    """Return the current device id, creating one when needed."""
    if 'device_id' not in session:
        session['device_id'] = str(uuid.uuid4())
    return session['device_id']


def owns_profile(profile):
    """Return whether the profile belongs to the current session."""
    return bool(profile and session.get('device_id') == profile.get('device_id'))


# Progress lives in SQLite. This set only covers the brief interval before
# the worker saves its first event (single-process local project).
ANALYSIS_RUNNING = set()
CHAT_RUNNING = set()
CHAT_LOCK = threading.Lock()


def profile_is_analyzed(profile):
    """Return whether an analysis exists for this profile (any saved field).

    A completed analysis may legitimately have an empty name, so "name is
    not null" alone is not a reliable definition of "analyzed".
    """
    if not profile:
        return False
    for field in ("name", "email", "field", "level", "summary"):
        if profile.get(field):
            return True
    for field in ("skills", "experience", "education"):
        # get_cv_profile parses these into lists; an empty list means absent.
        if profile.get(field):
            return True
    return False


def _db_backed_status(profile_id, profile):
    """Best-effort analysis status from the database when memory has none."""
    if profile.get('progress_json'):
        try:
            return json.loads(profile['progress_json'])
        except (ValueError, TypeError):
            pass
    if profile_id in ANALYSIS_RUNNING:
        return None  # analysis is live in this process; real events will arrive
    if db.has_match_results(profile_id):
        return {
            'stage': 'partial',
            'message': 'نتائج محفوظة من إصدار سابق؛ حالة اكتمال التحليل غير معروفة.',
            'data': {'source': 'database', 'redirect': f'/results/{profile_id}'},
        }
    if profile_is_analyzed(profile):
        return {
            'stage': 'partial',
            'message': 'اكتمل التحليل لكن لا توجد نتائج مطابقة محفوظة لهذه السيرة.',
            'data': {'source': 'database'},
        }
    return {
        'stage': 'failed',
        'message': 'لم يكتمل تحليل هذه السيرة الذاتية (ربما انقطع عند إعادة التشغيل). يرجى إعادة رفعها.',
        'data': {'source': 'database'},
    }


@app.route('/')
def index():
    """Render the upload page."""
    return render_template('index.html')


def public_profile(profile):
    """Send only presentation data; raw text and vectors stay on the server."""
    fields = ('profile_id', 'name', 'email', 'skills', 'experience', 'education',
              'field', 'level', 'summary', 'created_at', 'analysis_status')
    return {key: profile.get(key) for key in fields}


@app.errorhandler(413)
def upload_too_large(error):
    return jsonify({'error': 'حجم الملف يتجاوز الحد المسموح (16 MB).'}), 413


@app.route('/upload', methods=['POST'])
def upload_cv():
    """Save and start processing an uploaded CV."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file or not file.filename:
        return jsonify({'error': 'No file selected'}), 400

    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Only PDF files are accepted'}), 400

    header = file.stream.read(1024)
    file.stream.seek(0)
    if b'%PDF-' not in header:
        return jsonify({'error': 'Invalid PDF file'}), 400

    device_id = get_device_id()

    filename = f"{device_id}_{uuid.uuid4().hex}.pdf"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    try:
        raw_text = extract_text_from_pdf(filepath)
    finally:
        # Remove the uploaded file whether extraction succeeds or fails.
        try:
            os.remove(filepath)
        except OSError:
            pass

    if not raw_text:
        return jsonify({'error': 'Could not extract text from PDF'}), 422

    profile_id = db.insert_cv_profile(device_id=device_id, raw_text=raw_text)
    ANALYSIS_RUNNING.add(profile_id)

    thread = threading.Thread(
        target=analyze_and_match,
        args=(profile_id, raw_text)
    )
    thread.daemon = True
    try:
        thread.start()
    except RuntimeError:
        ANALYSIS_RUNNING.discard(profile_id)
        db.save_progress(profile_id, {'stage': 'failed', 'message': 'تعذر بدء التحليل. يرجى المحاولة مرة أخرى.'})
        return jsonify({'error': 'Could not start analysis'}), 503

    return jsonify({
        'success': True,
        'profile_id': profile_id,
        'redirect': f'/results/{profile_id}'
    })


@app.route('/results/<int:profile_id>')
def results(profile_id):
    """Render the results page for a profile."""
    profile = db.get_cv_profile(profile_id)
    if not profile:
        return render_template('index.html', error='Profile not found'), 404
    if not owns_profile(profile):
        return render_template('index.html', error='Unauthorized'), 403
    return render_template('index.html', profile_id=profile_id)


@app.route('/api/results/<int:profile_id>')
def api_results(profile_id):
    """Return profile and match results as JSON."""
    profile = db.get_cv_profile(profile_id)
    if not profile:
        return jsonify({'error': 'Profile not found'}), 404
    if not owns_profile(profile):
        return jsonify({'error': 'Unauthorized'}), 403

    match_results = db.get_match_results(profile_id)
    return jsonify({
        'profile': public_profile(profile),
        'results': match_results,
        'has_results': len(match_results) > 0,
        'is_analyzed': profile_is_analyzed(profile),
        'analysis': _db_backed_status(profile_id, profile)
    })


@app.route('/api/profile/<int:profile_id>')
def api_profile(profile_id):
    """Return profile data as JSON."""
    profile = db.get_cv_profile(profile_id)
    if not profile:
        return jsonify({'error': 'Profile not found'}), 404
    if not owns_profile(profile):
        return jsonify({'error': 'Unauthorized'}), 403
    return jsonify(public_profile(profile))




def search_matching_jobs(cv_embedding, all_jobs, limit=10):
    """Return (best jobs, degraded) after comparing their embeddings.

    degraded is True when the CV embedding or any job embedding was
    unavailable, meaning the returned order is not a real semantic ranking.
    """
    ranked_jobs = []
    degraded = not valid_embedding(cv_embedding)
    if degraded:
        cv_embedding = None
    if degraded:
        print("[search_matching_jobs] CV embedding unavailable - job order will not be semantic")

    for job in all_jobs:
        job_embedding = job.get('embedding')
        if isinstance(job_embedding, str):
            try:
                job_embedding = json.loads(job_embedding)
            except json.JSONDecodeError:
                job_embedding = None

        dimensions = len(cv_embedding) if cv_embedding else None
        if (not valid_embedding(job_embedding, dimensions)
                or job.get('embedding_model') != EMBEDDING_MODEL):
            job_text = f"{job.get('title', '')} {job.get('description', '')}"
            job_embedding = generate_embedding(job_text)
            if valid_embedding(job_embedding, dimensions):
                db.update_job_embedding(job['job_id'], job_embedding, EMBEDDING_MODEL)
            else:
                job_embedding = None
                degraded = True
                print(f"[search_matching_jobs] Embedding unavailable for job "
                      f"{job.get('job_id')} - its similarity will be 0")

        similarity = 0.0
        if cv_embedding and job_embedding:
            similarity = cosine_similarity(cv_embedding, job_embedding)

        job['_similarity'] = similarity
        ranked_jobs.append(job)

    ranked_jobs.sort(key=lambda job: job['_similarity'], reverse=True)
    print(f'[Semantic Search] Selected {min(limit, len(ranked_jobs))} jobs; degraded={degraded}')
    return ranked_jobs[:limit], degraded


def analyze_and_match(profile_id, raw_text):
    """Analyze a CV, rank jobs, and save matches in the background."""
    ANALYSIS_RUNNING.add(profile_id)

    def emit_progress(stage, message, data=None):
        payload = {'stage': stage, 'message': message}
        if data:
            payload['data'] = data
        db.save_progress(profile_id, payload)
        print(f'[Workflow] profile_id={profile_id} stage={stage}')
        try:
            socketio.emit('analysis_progress', payload, room=f'profile_{profile_id}')
            socketio.sleep(0.1)
        except Exception as e:
            print(f"[emit_progress] Error: {e}")

    try:
        emit_progress('cv_analysis', 'جاري تحليل السيرة الذاتية...')
        cv_data = analyze_cv(raw_text)

        if not cv_data:
            emit_progress('failed', 'فشل تحليل السيرة الذاتية، يرجى المحاولة مرة أخرى', {})
            return

        if cv_data.get("name"):
            emit_progress('cv_analysis', f"تم استخراج البيانات: {cv_data['name']}", {
                'name': cv_data.get('name'),
                'skills': cv_data.get('skills', [])
            })

        emit_progress('embedding', 'جاري إنشاء التمثيل الرقمي...')
        cv_text = '\n'.join(str(cv_data.get(key) or '') for key in
                            ('field', 'level', 'summary', 'skills', 'experience', 'education'))
        cv_embedding = generate_embedding(cv_text)

        db.update_cv_profile_analysis(
            profile_id=profile_id,
            name=cv_data.get('name'),
            email=cv_data.get('email'),
            skills=cv_data.get('skills', []),
            experience=cv_data.get('experience', []),
            education=cv_data.get('education', []),
            field=cv_data.get('field'),
            level=cv_data.get('level'),
            summary=cv_data.get('summary'),
            embedding=cv_embedding
        )
        db.update_cv_profile(profile_id, embedding_model=EMBEDDING_MODEL if cv_embedding else None)
        emit_progress('cv_analysis', 'تم تحليل السيرة الذاتية بنجاح', {'done': True})

        emit_progress('fetch_jobs', 'جاري جلب الوظائف المتاحة...')
        jobs = ensure_jobs_available()
        emit_progress('fetch_jobs', f"تم جلب {len(jobs)} وظيفة", {'count': len(jobs)})

        jobs, ranking_degraded = search_matching_jobs(cv_embedding, jobs)
        total = len(jobs)
        if not total:
            emit_progress('partial', 'تم تحليل السيرة، لكن لا توجد وظائف متاحة حالياً.', {'total_jobs': 0})
            return
        succeeded = 0
        failed = 0

        def score_one(job):
            """Score one job without letting a single failure stop the others."""
            try:
                return job, score_match(cv_data, job)
            except Exception as e:
                print(f"[analyze_and_match] Scoring failed for job {job.get('job_id')}: {e}")
                return job, None

        with ThreadPoolExecutor(max_workers=min(5, max(1, total))) as executor:
            futures = [executor.submit(score_one, job) for job in jobs]
            for idx, future in enumerate(as_completed(futures), 1):
                job, match_data = future.result()
                emit_progress('matching', f'جاري المطابقة {idx}/{total}: {job.get("title", "")}')

                if match_data:
                    db.insert_match_result(
                        profile_id=profile_id, job_id=job['job_id'],
                        similarity=round(job['_similarity'], 4),
                        match_score=match_data['match_score'],
                        strengths=match_data['strengths'],
                        missing_skills=match_data['missing_skills'],
                        recommendation=match_data['recommendation'],
                        ai_comment=match_data['ai_comment']
                    )
                    succeeded += 1
                else:
                    failed += 1
                socketio.sleep(0.05)

        ranking_note = ("تعذّر إنشاء التمثيل الرقمي - ترتيب الوظائف تقريبي وليس دلالياً."
                        if ranking_degraded else None)
        if ranking_degraded:
            print("[analyze_and_match] Semantic ranking degraded: "
                  "embedding unavailable for the CV or for one or more jobs")

        if succeeded == 0:
            emit_progress('failed', 'فشل تقييم جميع الوظائف، يرجى المحاولة مرة أخرى', {
                'total_jobs': total, 'succeeded': 0, 'failed': failed,
                'semantic_ranking': 'degraded' if ranking_degraded else 'ok',
            })
        elif failed > 0:
            emit_progress('partial', f'تم التحليل جزئياً: نجح تقييم {succeeded} من {total} وظيفة', {
                'total_jobs': total, 'succeeded': succeeded, 'failed': failed,
                'redirect': f'/results/{profile_id}',
                'semantic_ranking': 'degraded' if ranking_degraded else 'ok',
                'ranking_note': ranking_note,
            })
        else:
            emit_progress('complete', 'تم التحليل بنجاح!', {
                'total_jobs': total, 'redirect': f'/results/{profile_id}',
                'semantic_ranking': 'degraded' if ranking_degraded else 'ok',
                'ranking_note': ranking_note,
            })

    except Exception as e:
        print(f"[analyze_and_match] Error: {e}")
        import traceback
        traceback.print_exc()
        emit_progress('error', 'تعذر إكمال التحليل. يرجى المحاولة مرة أخرى.')
    finally:
        ANALYSIS_RUNNING.discard(profile_id)




@socketio.on('connect')
def handle_connect():
    print(f'[SocketIO] Client connected: {request.sid}')


@socketio.on('disconnect')
def handle_disconnect():
    print(f'[SocketIO] Client disconnected: {request.sid}')


@socketio.on('join')
def handle_join(data):
    from flask_socketio import join_room
    profile_id = event_profile_id(data)
    if not profile_id:
        return
    profile = db.get_cv_profile(profile_id)
    if not owns_profile(profile):
        print(f"[SocketIO] Unauthorized join attempt for profile_{profile_id} by {request.sid}")
        return
    room = f'profile_{profile_id}'
    join_room(room)
    emit('joined', {'room': room, 'profile_id': profile_id})
    # Re-deliver the tracked final analysis state to late joiners; when memory
    # has no entry (e.g. after a restart or page reload), fall back to the DB.
    try:
        pid = int(profile_id)
    except (TypeError, ValueError):
        pid = None
    final_status = _db_backed_status(pid, profile) if pid is not None else None
    if final_status:
        emit('analysis_progress', final_status)


@socketio.on('chat_message')
def handle_chat_message(data):
    """One conversation turn at a time so replies/history keep their order."""
    profile_id = event_profile_id(data)
    if not profile_id or not owns_profile(db.get_cv_profile(profile_id)):
        return
    with CHAT_LOCK:
        if profile_id in CHAT_RUNNING:
            emit('chat_response', {'sender': 'agent', 'message': 'يرجى انتظار الرد الحالي قبل إرسال رسالة أخرى.'})
            return
        CHAT_RUNNING.add(profile_id)
    try:
        process_chat_message(data)
    except Exception:
        print(f'[Chat] Failed to finish turn for profile_id={profile_id}')
        emit('chat_response', {'sender': 'agent', 'message': 'تعذر إكمال الرد. يرجى المحاولة مرة أخرى.'})
    finally:
        with CHAT_LOCK:
            CHAT_RUNNING.discard(profile_id)


def process_chat_message(data):
    profile_id = event_profile_id(data)
    user_message = data.get('message', '') if isinstance(data, dict) else ''
    if not isinstance(user_message, str) or len(user_message) > 4000:
        emit('chat_response', {'sender': 'agent', 'message': 'يرجى إرسال نص لا يتجاوز 4000 حرف.'})
        return
    user_message = user_message.strip()
    if not profile_id or not user_message:
        return

    profile = db.get_cv_profile(profile_id)
    if not owns_profile(profile):
        print(f"[SocketIO] Unauthorized chat_message for profile_{profile_id} by {request.sid}")
        return

    history = db.get_recent_chat_messages(profile_id)

    # Only the jobs already linked to this user's own match results are candidates.
    match_results = db.get_match_results(profile_id)
    jobs = [
        {'job_id': m['job_id'], 'title': m['job_title'], 'company': m['job_company']}
        for m in match_results
    ]

    requested_job_id = event_profile_id({'profile_id': data.get('job_id')})
    # Old result-card clients used job_id alone to request a cover letter.
    action = data.get('action', 'cover_letter' if 'job_id' in data else 'auto')
    if action not in ('auto', 'ask', 'cover_letter', 'improve_cv'):
        emit('chat_response', {'sender': 'agent', 'message': 'الإجراء المطلوب غير مدعوم.'})
        return

    allowed_job_ids = {m['job_id'] for m in match_results}
    if 'job_id' in data:
        if requested_job_id in allowed_job_ids:
            target_job_id = requested_job_id
            if action == 'ask':
                target_role = 'Chat Query Expert'
            elif action == 'cover_letter':
                target_role = 'Cover Letter Generator Expert'
            elif action == 'improve_cv':
                target_role = 'CV Improvement Expert'
            else:
                # Free text can still request either expert, but the selected
                # job is fixed: the model cannot silently pick a different job.
                target_role, _, _ = route_message(user_message, [j for j in jobs if j['job_id'] == requested_job_id], history=history)
        else:
            target_role = "NeedsClarification"
            target_job_id = None
    elif action == 'cover_letter':
        target_role, target_job_id = 'NeedsClarification', None
    elif action == 'ask':
        target_role, target_job_id = 'Chat Query Expert', None
    elif action == 'improve_cv':
        target_role, target_job_id = 'CV Improvement Expert', None
    else:
        target_role, target_job_id, _ = route_message(user_message, jobs, history=history)

    db.insert_chat_message(profile_id, 'user', user_message, target_job_id)

    response_text = ""
    if target_role == 'ServiceUnavailable':
        response_text = 'خدمة الذكاء الاصطناعي غير متاحة حالياً. يرجى المحاولة لاحقاً.'
    elif target_role == "NeedsClarification":
        response_text = (
            "لم أتمكن من تحديد الوظيفة المقصودة بدقة. "
            "هل يمكنك ذكر اسم الوظيفة كما هو في قائمة النتائج، أو استخدام زر "
            "«كتابة خطاب تقديم لهذه الوظيفة» بجانب الوظيفة المطلوبة؟"
        )
    elif target_role == "Cover Letter Generator Expert" and target_job_id:
        job_data = db.get_job(target_job_id)
        if job_data:
            response_text = generate_cover_letter(profile, job_data, profile_id, user_message=user_message, history=history)
        else:
            response_text = "عذراً، لم أتمكن من العثور على الوظيفة المحددة."
    elif target_role == 'CV Improvement Expert':
        selected_match = next((m for m in match_results if m['job_id'] == target_job_id), None)
        response_text = suggest_cv_improvements(profile, user_message, match=selected_match, history=history)
    else:
        response_text = answer_question(user_message, profile_id, jobs, history=history, selected_job_id=target_job_id)

    if response_text:
        db.insert_chat_message(profile_id, 'agent', response_text, target_job_id)

    emit('chat_response', {
        'sender': 'agent',
        'message': response_text,
        'job_id': target_job_id,
        'timestamp': datetime.now().isoformat()
    })


@socketio.on('request_chat_history')
def handle_chat_history(data):
    profile_id = event_profile_id(data)
    if not profile_id:
        return
    profile = db.get_cv_profile(profile_id)
    if not owns_profile(profile):
        print(f"[SocketIO] Unauthorized chat_history request for profile_{profile_id} by {request.sid}")
        return
    messages = db.get_chat_messages(profile_id)
    emit('chat_history', {'messages': messages})


def event_profile_id(data):
    """Accept integer ids and digit strings; reject containers and booleans."""
    if not isinstance(data, dict):
        return None
    value = data.get('profile_id')
    if type(value) is int:
        return value if 0 < value <= 9223372036854775807 else None
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 18:
        return int(value) or None
    return None


def run_local_server():
    """Single-process course demo; recovery happens only at server startup."""
    db.recover_interrupted_analyses()
    port = int(os.environ.get('PORT', 5000))
    # Debug off by default; enable explicitly with FLASK_DEBUG=true for local development.
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    # Bind to localhost by default; bind to all interfaces only with an explicit HOST.
    host = os.environ.get('HOST', '127.0.0.1')
    socketio.run(app, host=host, port=port, debug=debug,
                 allow_unsafe_werkzeug=host in ('127.0.0.1', 'localhost', '::1'))


if __name__ == '__main__':
    run_local_server()
