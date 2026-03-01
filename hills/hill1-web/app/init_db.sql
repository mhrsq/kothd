-- Corporate Portal Database
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    role TEXT DEFAULT 'user',
    email TEXT,
    full_name TEXT
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    author_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (author_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    filepath TEXT NOT NULL,
    uploaded_by INTEGER,
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (uploaded_by) REFERENCES users(id)
);

-- Default users (weak passwords — intended vulnerability)
INSERT INTO users (username, password, role, email, full_name) VALUES
    ('admin', 'admin123', 'admin', 'admin@fortress.local', 'System Administrator'),
    ('operator', 'oper@tor1', 'moderator', 'operator@fortress.local', 'System Operator'),
    ('guest', 'guest', 'user', 'guest@fortress.local', 'Guest User'),
    ('backup', 'b4ckup2026', 'admin', 'backup@fortress.local', 'Backup Service');

-- Some posts
INSERT INTO posts (title, content, author_id) VALUES
    ('Welcome to Web Fortress', 'This is the corporate portal for internal communications.', 1),
    ('Security Policy Update', 'All employees must update passwords by end of month.', 1),
    ('Maintenance Notice', 'System maintenance scheduled for this weekend.', 2);
