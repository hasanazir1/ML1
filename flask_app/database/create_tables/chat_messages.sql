-- جدول سجل الدردشة بين المستخدم و Match Agent
CREATE TABLE IF NOT EXISTS chat_messages (
    message_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id  INTEGER NOT NULL REFERENCES cv_profiles(profile_id),
    sender      TEXT NOT NULL,               -- 'user' | 'agent'
    message     TEXT NOT NULL,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);