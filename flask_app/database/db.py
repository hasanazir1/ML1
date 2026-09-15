"""SQLite connection and data access functions."""
import json
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "opportunity_agent.db")


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
    """Create tables and seed roles when the table is empty."""
    conn = get_connection()
    cur = conn.cursor()

    create_dir = os.path.join(os.path.dirname(__file__), "create_tables")
    for filename in sorted(os.listdir(create_dir)):
        if filename.endswith(".sql"):
            with open(os.path.join(create_dir, filename), "r", encoding="utf-8") as f:
                cur.executescript(f.read())

    cur.execute("SELECT COUNT(*) FROM llm_roles")
    if cur.fetchone()[0] == 0:
        import csv
        csv_path = os.path.join(os.path.dirname(__file__), "initial_data", "llm_roles.csv")
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cur.execute(
                    """INSERT INTO llm_roles (role, domain, specific_instructions,
                       background_context, few_shot_examples)
                       VALUES (?, ?, ?, ?, ?)""",
                    (row["role"], row["domain"], row["specific_instructions"],
                     row.get("background_context", ""), row.get("few_shot_examples", ""))
                )

    conn.commit()
    conn.close()


def insert_cv_profile(device_id, raw_text):
    """Insert a CV profile and return its id."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO cv_profiles (device_id, raw_text) VALUES (?, ?)",
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
               "field", "level", "summary", "embedding")
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
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"UPDATE cv_profiles SET {",".join(fields)} WHERE profile_id=?", values)
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


def update_job_embedding(job_id, embedding):
    """Save a job embedding."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE jobs SET embedding=? WHERE job_id=?",
        (json.dumps(embedding), job_id)
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
        "SELECT m.*, j.title AS job_title, j.company AS job_company, j.description AS job_description, j.link AS job_link, j.location AS job_location FROM match_results m INNER JOIN jobs j ON j.job_id=m.job_id WHERE m.profile_id=? ORDER BY m.match_score DESC",
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


def insert_chat_message(profile_id, sender, message):
    """Insert one chat message."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO chat_messages (profile_id,sender,message) VALUES (?,?,?)",
                (profile_id, sender, message))
    conn.commit()
    conn.close()


def get_chat_messages(profile_id):
    """Return chat messages for a profile."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM chat_messages WHERE profile_id=? ORDER BY created_at ASC",
                (profile_id,))
    rows = [dict_from_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


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
