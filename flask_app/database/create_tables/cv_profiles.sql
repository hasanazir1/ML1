-- جدول الملفات الشخصية (السير الذاتية المرفوعة)
CREATE TABLE IF NOT EXISTS cv_profiles (
    profile_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id    TEXT NOT NULL,
    name         TEXT,
    email        TEXT,
    raw_text     TEXT NOT NULL,
    skills       TEXT,                       -- JSON: ["Python", "Flask", ...]
    experience   TEXT,                       -- JSON: [{"title":..., "company":..., "years":...}]
    education    TEXT,                       -- JSON: [{"degree":..., "field":..., "institution":...}]
    field        TEXT,                       -- "Software Engineering"
    level        TEXT,                       -- "Junior" | "Mid" | "Senior"
    summary      TEXT,
    embedding    TEXT DEFAULT NULL,          -- JSON vector
    created_at   TEXT DEFAULT CURRENT_TIMESTAMP
);