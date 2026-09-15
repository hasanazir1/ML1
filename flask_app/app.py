"""Main Flask and Socket.IO application."""
import os
import json
import uuid
import threading
from datetime import datetime

from flask import Flask, render_template, request, jsonify, session
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv

load_dotenv()

from flask_app.database import db
db.init_db()

from flask_app.utils.pdf_parser import extract_text_from_pdf
from flask_app.utils.jobs_fetcher import ensure_jobs_available
from flask_app.utils.embedding_service import generate_embedding, cosine_similarity
from flask_app.agents.cv_analyzer import analyze_cv
from flask_app.agents.match_scorer import score_match
from flask_app.agents.chat_orchestrator import route_message
from flask_app.agents.chat_query import answer_question
from flask_app.agents.cover_letter import generate_cover_letter

app = Flask(__name__,
            template_folder='templates',
            static_folder='static')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24).hex())
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')


def get_device_id():
    """Return the current device id, creating one when needed."""
    if 'device_id' not in session:
        session['device_id'] = str(uuid.uuid4())
    return session['device_id']


def owns_profile(profile):
    """Return whether the profile belongs to the current session."""
    return bool(profile and session.get('device_id') == profile.get('device_id'))


@app.route('/')
def index():
    """Render the upload page."""
    return render_template('index.html')


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

    device_id = get_device_id()

    filename = f"{device_id}_{uuid.uuid4().hex}.pdf"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    raw_text = extract_text_from_pdf(filepath)
    if not raw_text:
        return jsonify({'error': 'Could not extract text from PDF'}), 422

    profile_id = db.insert_cv_profile(device_id=device_id, raw_text=raw_text)
    os.remove(filepath)

    thread = threading.Thread(
        target=analyze_and_match,
        args=(profile_id, raw_text)
    )
    thread.daemon = True
    thread.start()

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
        return render_template('index.html', error='Profile not found')
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
        'profile': profile,
        'results': match_results,
        'has_results': len(match_results) > 0,
        'is_analyzed': profile.get('name') is not None
    })


@app.route('/api/profile/<int:profile_id>')
def api_profile(profile_id):
    """Return profile data as JSON."""
    profile = db.get_cv_profile(profile_id)
    if not profile:
        return jsonify({'error': 'Profile not found'}), 404
    return jsonify(profile)




def search_matching_jobs(cv_embedding, all_jobs, limit=10):
    """Return the best jobs after comparing their embeddings."""
    ranked_jobs = []

    for job in all_jobs:
        job_embedding = job.get('embedding')
        if isinstance(job_embedding, str):
            try:
                job_embedding = json.loads(job_embedding)
            except json.JSONDecodeError:
                job_embedding = None

        if not job_embedding:
            job_text = f"{job.get('title', '')} {job.get('description', '')}"
            job_embedding = generate_embedding(job_text)
            if job_embedding:
                conn = db.get_connection()
                conn.execute(
                    "UPDATE jobs SET embedding=? WHERE job_id=?",
                    (json.dumps(job_embedding), job.get('job_id'))
                )
                conn.commit()
                conn.close()

        similarity = 0.0
        if cv_embedding and job_embedding:
            similarity = cosine_similarity(cv_embedding, job_embedding)

        job['_similarity'] = similarity
        ranked_jobs.append(job)

    ranked_jobs.sort(key=lambda job: job['_similarity'], reverse=True)
    return ranked_jobs[:limit]


def analyze_and_match(profile_id, raw_text):
    """Analyze a CV, rank jobs, and save matches in the background."""
    def emit_progress(stage, message, data=None):
        payload = {'stage': stage, 'message': message}
        if data:
            payload['data'] = data
        try:
            socketio.emit('analysis_progress', payload, room=f'profile_{profile_id}')
            socketio.sleep(0.1)
        except Exception as e:
            print(f"[emit_progress] Error: {e}")

    try:
        emit_progress('cv_analysis', 'جاري تحليل السيرة الذاتية...')
        cv_data = analyze_cv(raw_text)

        if cv_data.get("name"):
            emit_progress('cv_analysis', f"تم استخراج البيانات: {cv_data['name']}", {
                'name': cv_data.get('name'),
                'skills': cv_data.get('skills', [])
            })

        emit_progress('embedding', 'جاري إنشاء التمثيل الرقمي...')
        cv_text = f"{cv_data.get('summary', '')} {' '.join(cv_data.get('skills', []))}"
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
        emit_progress('cv_analysis', 'تم تحليل السيرة الذاتية بنجاح', {'done': True})

        emit_progress('fetch_jobs', 'جاري جلب الوظائف المتاحة...')
        jobs = ensure_jobs_available()
        emit_progress('fetch_jobs', f"تم جلب {len(jobs)} وظيفة", {'count': len(jobs)})

        jobs = search_matching_jobs(cv_embedding, jobs)
        total = len(jobs)
        for idx, job in enumerate(jobs, 1):
            emit_progress('matching', f'جاري المطابقة {idx}/{total}: {job.get("title", "")}')

            match_data = score_match(cv_data, job)
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
            socketio.sleep(0.05)

        emit_progress('complete', 'تم التحليل بنجاح!', {
            'total_jobs': total, 'redirect': f'/results/{profile_id}'
        })

    except Exception as e:
        print(f"[analyze_and_match] Error: {e}")
        import traceback
        traceback.print_exc()
        emit_progress('error', f'حدث خطأ: {str(e)}')




@socketio.on('connect')
def handle_connect():
    print(f'[SocketIO] Client connected: {request.sid}')


@socketio.on('disconnect')
def handle_disconnect():
    print(f'[SocketIO] Client disconnected: {request.sid}')


@socketio.on('join')
def handle_join(data):
    from flask_socketio import join_room
    profile_id = data.get('profile_id')
    if profile_id:
        room = f'profile_{profile_id}'
        join_room(room)
        emit('joined', {'room': room, 'profile_id': profile_id})


@socketio.on('chat_message')
def handle_chat_message(data):
    profile_id = data.get('profile_id')
    user_message = data.get('message', '')
    if not profile_id or not user_message:
        return

    db.insert_chat_message(profile_id, 'user', user_message)
    profile = db.get_cv_profile(profile_id)
    jobs = db.get_all_jobs()
    target_role, target_job_id, _ = route_message(user_message, jobs)

    response_text = ""
    if target_role == "Cover Letter Generator Expert" and target_job_id:
        job_data = db.get_job(target_job_id)
        if job_data:
            response_text = generate_cover_letter(profile, job_data, profile_id)
        else:
            response_text = "عذراً، لم أتمكن من العثور على الوظيفة المحددة."
    else:
        response_text = answer_question(user_message, profile_id, jobs)

    if response_text:
        db.insert_chat_message(profile_id, 'agent', response_text)

    emit('chat_response', {
        'sender': 'agent',
        'message': response_text,
        'timestamp': datetime.now().isoformat()
    })


@socketio.on('request_chat_history')
def handle_chat_history(data):
    profile_id = data.get('profile_id')
    if profile_id:
        messages = db.get_chat_messages(profile_id)
        emit('chat_history', {'messages': messages})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    print(f"\n{'='*50}")
    print(f"AI Opportunity Agent on http://localhost:{port}")
    print(f"{'='*50}\n")
    socketio.run(app, host='0.0.0.0', port=port, debug=debug, allow_unsafe_werkzeug=True)
