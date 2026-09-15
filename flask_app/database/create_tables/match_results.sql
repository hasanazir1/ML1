-- جدول نتائج المطابقة بين CV ووظيفة
CREATE TABLE IF NOT EXISTS match_results (
    match_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id      INTEGER NOT NULL REFERENCES cv_profiles(profile_id),
    job_id          INTEGER NOT NULL REFERENCES jobs(job_id),
    similarity      REAL,                    -- Cosine similarity الخام (0-1)
    match_score     INTEGER,                 -- 0-100 من الـ LLM
    strengths       TEXT,                    -- JSON array
    missing_skills  TEXT,                    -- JSON array
    recommendation  TEXT,                    -- "Highly Recommended" | "Partial Match" | "Not Recommended"
    ai_comment      TEXT,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);