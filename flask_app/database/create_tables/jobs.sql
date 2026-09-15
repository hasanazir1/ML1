-- جدول الوظائف (مشتركة بين كل المستخدمين)
CREATE TABLE IF NOT EXISTS jobs (
    job_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    company      TEXT,
    description  TEXT NOT NULL,
    link         TEXT UNIQUE,
    location     TEXT,
    published_at TEXT,
    embedding    TEXT DEFAULT NULL,
    fetched_at   TEXT DEFAULT CURRENT_TIMESTAMP
);