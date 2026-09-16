"""SQLite connection and data access functions."""
import json
import os
import sqlite3
import csv
from contextlib import closing

DB_PATH = os.environ.get('DATABASE_PATH') or os.path.join(os.path.dirname(__file__), "opportunity_agent.db")


def get_connection():
    """Return a configured SQLite connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def dict_from_row(row):
    """Convert a row to a dictionary."""
    return dict(row) if row else None


def _parse_list_field(d, field):
    """Parse one JSON list field in place."""
    if d.get(field):
        try:
            d[field] = json.loads(d[field])
        except (json.JSONDecodeError, TypeError):
            d[field] = []
    else:
        d[field] = []


def _parse_embedding(d):
    """Parse one JSON embedding in place."""
    if d.get("embedding"):
        try:
            d["embedding"] = json.loads(d["embedding"])
        except (json.JSONDecodeError, TypeError):
            d["embedding"] = None
    else:
        d["embedding"] = None

def init_db():
    """Create/upgrade tables without deleting data; CSV owns role configuration."""
    conn = get_connection()
    cur = conn.cursor()

    create_dir = os.path.join(os.path.dirname(__file__), "create_tables")
    for filename in sorted(os.listdir(create_dir)):
        if filename.endswith(".sql"):
            with open(os.path.join(create_dir, filename), "r", encoding="utf-8") as f:
                cur.executescript(f.read())

    # Small additive migration: old profiles remain explicitly 'legacy'.
    additions = {
        'cv_profiles': {'analysis_status': "TEXT DEFAULT 'legacy'", 'progress_json': 'TEXT',
                        'embedding_model': 'TEXT'},
        'jobs': {'embedding_model': 'TEXT'},
        'chat_messages': {'job_id': 'INTEGER REFERENCES jobs(job_id)'},
    }
    for table, columns in additions.items():
        existing = {row[1] for row in cur.execute(f'PRAGMA table_info({table})')}
        for column, declaration in columns.items():
            if column not in existing:
                cur.execute(f'ALTER TABLE {table} ADD COLUMN {column} {declaration}')
    cur.execute('CREATE INDEX IF NOT EXISTS matches_profile ON match_results(profile_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS messages_profile ON chat_messages(profile_id, message_id)')

    csv_path = os.path.join(os.path.dirname(__file__), "initial_data", "llm_roles.csv")
    with open(csv_path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cur.execute(
                """INSERT INTO llm_roles (role, domain, specific_instructions,
                   background_context, few_shot_examples) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(role) DO UPDATE SET domain=excluded.domain,
                   specific_instructions=excluded.specific_instructions,
                   background_context=excluded.background_context,
                   few_shot_examples=excluded.few_shot_examples""",
                (row['role'], row['domain'], row['specific_instructions'],
                 row.get('background_context', ''), row.get('few_shot_examples', '')))

    conn.commit()
    conn.close()


def insert_cv_profile(device_id, raw_text):
    """Insert a CV profile and return its id."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO cv_profiles (device_id, raw_text, analysis_status) VALUES (?, ?, 'pending')",
        (device_id, raw_text)
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def get_cv_profile(profile_id):
    """Return one CV profile by id."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM cv_profiles WHERE profile_id=?", (profile_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        d = dict_from_row(row)
        _parse_list_field(d, "skills")
        _parse_list_field(d, "experience")
        _parse_list_field(d, "education")
        _parse_embedding(d)
        return d
    return None


def update_cv_profile(profile_id, **kwargs):
    """Update allowed CV profile fields."""
    allowed = ("name", "email", "skills", "experience", "education",
               "field", "level", "summary", "embedding", "embedding_model")
    fields = []
    values = []
    for key, val in kwargs.items():
        if key in allowed:
            if key in ("skills", "experience", "education") and isinstance(val, list):
                val = json.dumps(val, ensure_ascii=False)
            elif key == "embedding" and isinstance(val, list):
                val = json.dumps(val)
            fields.append(f"{key}=?")
            values.append(val)
    if not fields:
        return
    values.append(profile_id)
    set_clause = ",".join(fields)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"UPDATE cv_profiles SET {set_clause} WHERE profile_id=?", values)
    conn.commit()
    conn.close()


def update_cv_profile_analysis(profile_id, name, email, skills, experience, education,
                                 field, level, summary, embedding):
    """Save analysis fields for a CV profile."""
    update_cv_profile(profile_id, name=name, email=email, skills=skills,
                      experience=experience, education=education, field=field,
                      level=level, summary=summary, embedding=embedding)


def get_all_jobs():
    """Return all jobs ordered by date and id."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM jobs ORDER BY published_at DESC, job_id DESC")
    rows = cur.fetchall()
    conn.close()
    return [dict_from_row(r) for r in rows]


def get_recent_jobs(limit=20):
    """Return the most recent jobs."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM jobs ORDER BY published_at DESC, job_id DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return [dict_from_row(r) for r in rows]



def get_job(job_id):
    """Return one job by id."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,))
    row = cur.fetchone()
    conn.close()
    return dict_from_row(row)


def update_job_embedding(job_id, embedding, model=None):
    """Save a job embedding."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE jobs SET embedding=?, embedding_model=? WHERE job_id=?",
        (json.dumps(embedding), model, job_id)
    )
    conn.commit()
    conn.close()


def insert_job(title, company, description, link, location, published_at, embedding=None):
    """Insert a job and return its id, or None for a duplicate link."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO jobs (title,company,description,link,location,published_at,embedding) VALUES (?,?,?,?,?,?,?)",
            (title, company, description, link, location, published_at,
             json.dumps(embedding) if embedding else None))
        jid = cur.lastrowid
        conn.commit()
        conn.close()
        return jid
    except sqlite3.IntegrityError:
        conn.close()
        return None


def count_jobs():
    """Return the number of jobs."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM jobs")
    c = cur.fetchone()[0]
    conn.close()
    return c
def insert_match_result(profile_id, job_id, similarity, match_score, strengths,
                        missing_skills, recommendation, ai_comment):
    """Insert one match result."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO match_results (profile_id,job_id,similarity,match_score,strengths,missing_skills,recommendation,ai_comment) VALUES (?,?,?,?,?,?,?,?)",
        (profile_id, job_id, similarity, match_score, json.dumps(strengths, ensure_ascii=False),
         json.dumps(missing_skills, ensure_ascii=False), recommendation, ai_comment))
    conn.commit()
    conn.close()


def get_match_results(profile_id):
    """Return match results with job details."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT m.*, j.title AS job_title, j.company AS job_company, j.description AS job_description, j.link AS job_link, j.location AS job_location FROM match_results m INNER JOIN jobs j ON j.job_id=m.job_id WHERE m.profile_id=? ORDER BY m.match_score DESC, m.job_id ASC",
        (profile_id,))
    rows = cur.fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict_from_row(r)
        for fld in ("strengths", "missing_skills"):
            _parse_list_field(d, fld)
        results.append(d)
    return results


def has_match_results(profile_id):
    """Return whether a profile has match results."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM match_results WHERE profile_id=?", (profile_id,))
    c = cur.fetchone()[0]
    conn.close()
    return c > 0


def insert_chat_message(profile_id, sender, message, job_id=None):
    """Insert one chat message."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO chat_messages (profile_id,sender,message,job_id) VALUES (?,?,?,?)",
                (profile_id, sender, message, job_id))
    conn.commit()
    conn.close()


def get_chat_messages(profile_id):
    """Return chat messages for a profile."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM chat_messages WHERE profile_id=? ORDER BY message_id ASC",
                (profile_id,))
    rows = [dict_from_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_recent_chat_messages(profile_id, limit=6):
    """Return a bounded conversation window in chronological order."""
    with closing(get_connection()) as conn:
        rows = conn.execute(
            'SELECT sender,message,job_id FROM chat_messages WHERE profile_id=? '
            'ORDER BY message_id DESC LIMIT ?', (profile_id, limit)).fetchall()
    return [dict(row) for row in reversed(rows)]


def save_progress(profile_id, payload):
    """Persist the same event that the browser receives through Socket.IO."""
    status = {'complete': 'completed', 'error': 'failed'}.get(payload['stage'], payload['stage'])
    with closing(get_connection()) as conn, conn:
        conn.execute('UPDATE cv_profiles SET analysis_status=?, progress_json=? WHERE profile_id=?',
                     (status, json.dumps(payload, ensure_ascii=False), profile_id))


def recover_interrupted_analyses():
    """Call ONCE at single-process server startup, before accepting uploads.

    Work is not resumed automatically. Existing results stay available and the
    user is told to re-upload; a new upload creates a separate profile.
    """
    with closing(get_connection()) as conn, conn:
        rows = conn.execute("SELECT profile_id FROM cv_profiles WHERE analysis_status IN "
                            "('pending','cv_analysis','embedding','fetch_jobs','matching')").fetchall()
        for row in rows:
            pid = row['profile_id']
            count = conn.execute('SELECT COUNT(*) FROM match_results WHERE profile_id=?', (pid,)).fetchone()[0]
            stage = 'partial' if count else 'failed'
            payload = {'stage': stage, 'message': 'انقطع التحليل عند إيقاف الخادم. يرجى إعادة رفع السيرة لإجراء تحليل جديد.',
                       'data': {'interrupted': True, 'succeeded': count}}
            conn.execute('UPDATE cv_profiles SET analysis_status=?,progress_json=? WHERE profile_id=?',
                         (stage, json.dumps(payload, ensure_ascii=False), pid))


def get_llm_role(role):
    """Return one role configuration."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM llm_roles WHERE role=?", (role,))
    row = cur.fetchone()
    conn.close()
    return dict_from_row(row)


def get_all_llm_roles():
    """Return all role configurations."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM llm_roles")
    rows = [dict_from_row(r) for r in cur.fetchall()]
    conn.close()
    return rows
