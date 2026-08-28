import json
import sqlite3
import os
import hashlib
import hmac
import base64
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

# Load environment variable for Postgres support
DATABASE_URL = os.environ.get("DATABASE_URL")

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / 'digitz_ai.db'

DEFAULT_BRANDS = []

# --- Password Hashing (PBKDF2 SHA-256) ---
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    rounds = 100000
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, rounds)
    salt_b64 = base64.b64encode(salt).decode('utf-8')
    key_b64 = base64.b64encode(key).decode('utf-8')
    return f"{rounds}${salt_b64}${key_b64}"

def verify_password(password: str, hashed: str) -> bool:
    try:
        parts = hashed.split('$')
        if len(parts) != 3:
            return False
        rounds_str, salt_b64, key_b64 = parts
        rounds = int(rounds_str)
        salt = base64.b64decode(salt_b64.encode('utf-8'))
        key = base64.b64decode(key_b64.encode('utf-8'))
        new_key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, rounds)
        return hmac.compare_digest(key, new_key)
    except Exception:
        return False

# --- Connection Handler ---
def get_conn():
    if DATABASE_URL and psycopg2:
        try:
            conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)
            return conn
        except Exception as e:
            print(f"PostgreSQL connection failed: {e}. Falling back to SQLite.")
    
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn

def _now_iso() -> str:
    return datetime.utcnow().isoformat() + 'Z'

def _row_to_dict(row):
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    # If it is a sqlite3.Row or psycopg2 DictRow
    return {key: row[key] for key in row.keys()}

def _execute_query(sql: str, params: tuple = ()) -> None:
    conn = get_conn()
    cursor = conn.cursor()
    if DATABASE_URL and psycopg2:
        sql = sql.replace('?', '%s')
    cursor.execute(sql, params)
    conn.commit()
    conn.close()

def _create_indexes(cursor):
    """Create SQLite indexes for query performance if they don't exist."""
    import sys
    indexes = [
        ("idx_vectors_document_id", "vectors", "document_id"),
        ("idx_vectors_created_at", "vectors", "created_at"),
        ("idx_vectors_doc_chunk", "vectors", "document_id, chunk_index"),
        ("idx_documents_brand_key", "documents", "brand_key"),
        ("idx_documents_uploaded_at", "documents", "uploaded_at"),
        ("idx_queries_brand_key", "queries", "brand_key"),
        ("idx_queries_created_at", "queries", "created_at"),
        ("idx_chat_sessions_brand_key", "chat_sessions", "brand_key"),
        ("idx_chat_sessions_user_id", "chat_sessions", "user_id"),
        ("idx_chat_messages_session_id", "chat_messages", "session_id"),
    ]
    for idx_name, table, column in indexes:
        try:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({column})")
            print(f"[DB] Index {idx_name} on {table}({column}) OK")
        except Exception as e:
            print(f"[DB] Index {idx_name} warning: {e}")
    sys.stdout.flush()


def explain_query_plan(sql: str, params: tuple = ()) -> str:
    """Run EXPLAIN QUERY PLAN and return results for debugging."""
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(f"EXPLAIN QUERY PLAN {sql}", params)
        rows = cursor.fetchall()
        plan = "\n".join(str(dict(r)) for r in rows)
        conn.close()
        return plan
    except Exception as e:
        return f"EXPLAIN failed: {e}"


def _has_column(cursor, table: str, column: str) -> bool:
    if DATABASE_URL and psycopg2:
        cursor.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
            (table.lower(), column.lower())
        )
        return cursor.fetchone() is not None
    else:
        try:
            info = cursor.execute(f"PRAGMA table_info({table})").fetchall()
            return any(row['name'].lower() == column.lower() for row in info)
        except Exception:
            return False

# --- Schema Initialization ---
def init_db() -> None:
    conn = get_conn()
    cursor = conn.cursor()

    # Create Users
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TEXT NOT NULL
        )
    ''')

    # Create Brands
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS brands (
            key TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            color TEXT,
            description TEXT,
            industry TEXT,
            website TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            logo_url TEXT,
            ai_prompt TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT
        )
    ''')

    # Re-verify brands columns
    if not _has_column(cursor, 'brands', 'ai_prompt'):
        cursor.execute('ALTER TABLE brands ADD COLUMN ai_prompt TEXT')
    if not _has_column(cursor, 'brands', 'description'):
        cursor.execute('ALTER TABLE brands ADD COLUMN description TEXT')
    if not _has_column(cursor, 'brands', 'industry'):
        cursor.execute('ALTER TABLE brands ADD COLUMN industry TEXT')
    if not _has_column(cursor, 'brands', 'website'):
        cursor.execute('ALTER TABLE brands ADD COLUMN website TEXT')
    if not _has_column(cursor, 'brands', 'status'):
        cursor.execute("ALTER TABLE brands ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
    if not _has_column(cursor, 'brands', 'logo_url'):
        cursor.execute('ALTER TABLE brands ADD COLUMN logo_url TEXT')
    if not _has_column(cursor, 'brands', 'updated_at'):
        cursor.execute('ALTER TABLE brands ADD COLUMN updated_at TEXT')

    # Users table migration — team-management fields (name, status, last login, brand access)
    if not _has_column(cursor, 'users', 'name'):
        cursor.execute('ALTER TABLE users ADD COLUMN name TEXT')
    if not _has_column(cursor, 'users', 'status'):
        cursor.execute("ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
    if not _has_column(cursor, 'users', 'last_login'):
        cursor.execute('ALTER TABLE users ADD COLUMN last_login TEXT')
    if not _has_column(cursor, 'users', 'brand_keys'):
        cursor.execute("ALTER TABLE users ADD COLUMN brand_keys TEXT NOT NULL DEFAULT ''")
    if not _has_column(cursor, 'users', 'invited_by'):
        cursor.execute('ALTER TABLE users ADD COLUMN invited_by TEXT')

    # Create Conversations
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            brand_key TEXT NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(brand_key) REFERENCES brands(key) ON DELETE CASCADE
        )
    ''')

    # Create Messages
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            sender TEXT NOT NULL,
            text TEXT NOT NULL,
            inferred INTEGER DEFAULT 0,
            source_docs TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )
    ''')

    # Create Documents
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            brand_key TEXT NOT NULL,
            title TEXT NOT NULL,
            filename TEXT NOT NULL,
            content TEXT NOT NULL,
            size INTEGER,
            type TEXT,
            folder TEXT,
            status TEXT,
            uploaded_at TEXT NOT NULL,
            FOREIGN KEY(brand_key) REFERENCES brands(key) ON DELETE CASCADE
        )
    ''')

    # Vectors Table Rebuild (Drop if it has older column layout)
    if _has_column(cursor, 'vectors', 'chunk_count'):
        cursor.execute('DROP TABLE IF EXISTS vectors')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vectors (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            chunk_index INTEGER,
            chunk_text TEXT,
            embedding TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
        )
    ''')

    # Create Queries
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS queries (
            id TEXT PRIMARY KEY,
            query_text TEXT NOT NULL,
            brand_key TEXT,
            mode TEXT,
            status TEXT,
            answer_excerpt TEXT,
            response_time REAL,
            similarity_score REAL,
            retrieved_chunks INTEGER,
            session_id TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(brand_key) REFERENCES brands(key) ON DELETE CASCADE
        )
    ''')

    # --- Backwards-compatible migration for older DB files ---
    # If the app was run with an older schema, ensure all columns exist.
    if not _has_column(cursor, 'queries', 'answer_excerpt'):
        cursor.execute('ALTER TABLE queries ADD COLUMN answer_excerpt TEXT')
    if not _has_column(cursor, 'queries', 'response_time'):
        cursor.execute('ALTER TABLE queries ADD COLUMN response_time REAL')
    if not _has_column(cursor, 'queries', 'similarity_score'):
        cursor.execute('ALTER TABLE queries ADD COLUMN similarity_score REAL')
    if not _has_column(cursor, 'queries', 'retrieved_chunks'):
        cursor.execute('ALTER TABLE queries ADD COLUMN retrieved_chunks INTEGER')
    if not _has_column(cursor, 'queries', 'session_id'):
        cursor.execute('ALTER TABLE queries ADD COLUMN session_id TEXT')
    if not _has_column(cursor, 'queries', 'mode'):
        cursor.execute("ALTER TABLE queries ADD COLUMN mode TEXT")
    if not _has_column(cursor, 'queries', 'status'):
        cursor.execute("ALTER TABLE queries ADD COLUMN status TEXT")


    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            brand_key TEXT,
            brand_id TEXT,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_pinned INTEGER DEFAULT 0,
            is_archived INTEGER DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            question TEXT,
            answer TEXT,
            sources TEXT,
            attachments TEXT,
            retrieved_documents TEXT,
            response_time REAL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
        )
    ''')

    # Backwards-compatible migration for older DB files
    # SQLite keeps old schemas around; if we add columns in newer versions we must ensure they exist.
    for col, ddl in [
        ('brand_id', 'ALTER TABLE chat_sessions ADD COLUMN brand_id TEXT'),
        ('updated_at', 'ALTER TABLE chat_sessions ADD COLUMN updated_at TEXT NOT NULL DEFAULT (datetime("now"))'),
        ('is_pinned', 'ALTER TABLE chat_sessions ADD COLUMN is_pinned INTEGER DEFAULT 0'),
        ('is_archived', 'ALTER TABLE chat_sessions ADD COLUMN is_archived INTEGER DEFAULT 0'),
        ('sources', 'ALTER TABLE chat_messages ADD COLUMN sources TEXT'),
        ('attachments', 'ALTER TABLE chat_messages ADD COLUMN attachments TEXT'),
    ]:
        table = 'chat_sessions' if col in ['brand_id', 'updated_at', 'is_pinned', 'is_archived'] else 'chat_messages'
        try:
            if not _has_column(cursor, table, col):
                cursor.execute(ddl)
        except Exception as e:
            # If migration introspection fails for some reason, continue.
            # We'll also have a runtime retry guard in create_chat_session().
            print(f"DB migration warning: could not ensure {table}.{col}: {e}")



    # Create Campaigns
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS campaigns (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            brand_key TEXT,
            objective TEXT,
            target_audience TEXT,
            budget REAL,
            timeline TEXT,
            status TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(brand_key) REFERENCES brands(key) ON DELETE CASCADE
        )
    ''')

    # Create Reports
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id TEXT PRIMARY KEY,
            brand_key TEXT,
            report_type TEXT,
            period TEXT,
            file_name TEXT,
            status TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(brand_key) REFERENCES brands(key) ON DELETE CASCADE
        )
    ''')

    # Create Notifications
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id TEXT PRIMARY KEY,
            type TEXT,
            message TEXT,
            payload TEXT,
            read INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    ''')

    # Create Analytics
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS analytics (
            id TEXT PRIMARY KEY,
            metric_type TEXT NOT NULL,
            metric_value REAL NOT NULL,
            brand_key TEXT,
            timestamp TEXT NOT NULL
        )
    ''')

    # Create Subscriptions
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subscriptions (
            id TEXT PRIMARY KEY,
            user_id TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL,
            plan TEXT NOT NULL,
            amount REAL,
            billing_period TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')

    # Create Settings
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    conn.commit()

    # --- SQLite Performance Indexes ---
    _create_indexes(cursor)

    # --- Seed Data Insertion ---
    # 1. Seed default brands from configuration (empty by default)
    for brand in DEFAULT_BRANDS:
        cursor.execute("SELECT 1 FROM brands WHERE key = ?", (brand['key'],))
        if cursor.fetchone() is None:
            now = _now_iso()
            cursor.execute('''
                INSERT INTO brands (key, name, color, description, industry, website, status, created_at, updated_at, ai_prompt)
                VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
            ''', (brand['key'], brand['name'], brand['color'], brand['description'], brand['industry'], brand['website'], now, now, f"You are an assistant for {brand['name']}. Focus on their guidelines."))

    # 2. Seed default admin user
    cursor.execute("SELECT 1 FROM users WHERE email = ?", ('admin@digitz.co',))
    if cursor.fetchone() is None:
        admin_id = str(uuid4())
        hashed = hash_password("password123")
        cursor.execute('''
            INSERT INTO users (id, email, password_hash, role, created_at, name, status)
            VALUES (?, ?, ?, 'admin', ?, ?, 'active')
        ''', (admin_id, 'admin@digitz.co', hashed, _now_iso(), 'Admin User'))
        
        # Seed Subscription for Admin
        cursor.execute('''
            INSERT INTO subscriptions (id, user_id, status, plan, amount, billing_period, updated_at)
            VALUES (?, ?, 'active', 'enterprise', 199.00, 'monthly', ?)
        ''', (str(uuid4()), admin_id, _now_iso()))

    # 3. Seed default settings
    default_settings = {
        'active_provider': 'groq',
        'openai_key': '',
        'groq_key': os.environ.get('GROQ_API_KEY', ''),
        'gemini_key': '',
        'deepseek_key': '',
        'anthropic_key': '',
    }
    for k, v in default_settings.items():
        cursor.execute("SELECT 1 FROM settings WHERE key = ?", (k,))
        if cursor.fetchone() is None:
            cursor.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (k, v))

    # 4. Seed active company if one exists in brands but no active setting yet.
    cursor.execute("SELECT value FROM settings WHERE key = 'active_company'")
    if cursor.fetchone() is None:
        cursor.execute('SELECT key FROM brands ORDER BY created_at LIMIT 1')
        row = cursor.fetchone()
        if row and row['key']:
            cursor.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ('active_company', row['key']))

    conn.commit()
    conn.close()

# --- Reset Function ---
def reset_uploaded_documents() -> None:
    with get_conn() as conn:
        conn.execute('DELETE FROM vectors')
        conn.execute('DELETE FROM documents')
        conn.execute('DELETE FROM queries')
        conn.execute('DELETE FROM chat_messages')
        conn.execute('DELETE FROM chat_sessions')
        conn.commit()

# --- Users Logic ---
def create_user(email: str, password_raw: str, role: str = 'user') -> dict:
    user_id = str(uuid4())
    hashed = hash_password(password_raw)
    now = _now_iso()
    with get_conn() as conn:
        conn.execute('''
            INSERT INTO users (id, email, password_hash, role, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, email, hashed, role, now))
        conn.commit()
    return {'id': user_id, 'email': email, 'role': role}

def get_user_by_email(email: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return _row_to_dict(row)

def get_users() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        users = [_row_to_dict(r) for r in rows]
    for u in users:
        u.pop('password_hash', None)  # never leak hashes to the API layer
        if not u.get('name'):
            u['name'] = u['email'].split('@')[0].replace('.', ' ').title()
        brand_keys = [k for k in (u.get('brand_keys') or '').split(',') if k]
        u['brand_keys'] = brand_keys
        u['brands_count'] = len(brand_keys) if u['role'] != 'admin' else len(get_brands())
    return users

def get_user_by_id(user_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _row_to_dict(row)

def update_user_status(user_id: str, status: str) -> dict | None:
    with get_conn() as conn:
        conn.execute("UPDATE users SET status = ? WHERE id = ?", (status, user_id))
        conn.commit()
    return get_user_by_id(user_id)

def update_user_role(user_id: str, role: str, brand_keys: list[str] | None = None) -> dict | None:
    with get_conn() as conn:
        if brand_keys is not None:
            conn.execute("UPDATE users SET role = ?, brand_keys = ? WHERE id = ?", (role, ','.join(brand_keys), user_id))
        else:
            conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        conn.commit()
    return get_user_by_id(user_id)

def update_last_login(user_id: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (_now_iso(), user_id))
        conn.commit()

def invite_user(email: str, role: str, name: str | None, brand_keys: list[str], invited_by: str) -> dict:
    """Creates a real account with a random temp password so it can log in immediately.
    NOTE: no SMTP is configured in this project, so no email is actually sent — the
    temp password is returned to the caller (admin) to share manually. See routers/users.py."""
    import secrets
    temp_password = secrets.token_urlsafe(9)
    user_id = str(uuid4())
    hashed = hash_password(temp_password)
    now = _now_iso()
    display_name = name or email.split('@')[0].replace('.', ' ').title()
    with get_conn() as conn:
        conn.execute('''
            INSERT INTO users (id, email, password_hash, role, created_at, name, status, brand_keys, invited_by)
            VALUES (?, ?, ?, ?, ?, ?, 'invited', ?, ?)
        ''', (user_id, email, hashed, role, now, display_name, ','.join(brand_keys), invited_by))
        conn.commit()
    return {'id': user_id, 'email': email, 'role': role, 'name': display_name, 'temp_password': temp_password}

# --- Subscriptions Logic ---
def create_subscription(user_id: str, status: str = 'active', plan: str = 'free', amount: float = 0.0, billing_period: str = 'monthly') -> dict:
    sub_id = str(uuid4())
    now = _now_iso()
    with get_conn() as conn:
        conn.execute('''
            INSERT INTO subscriptions (id, user_id, status, plan, amount, billing_period, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (sub_id, user_id, status, plan, amount, billing_period, now))
        conn.commit()
    return get_subscription(user_id)

def get_subscription(user_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM subscriptions WHERE user_id = ?", (user_id,)).fetchone()
        return _row_to_dict(row)

def update_subscription(user_id: str, status: str, plan: str, amount: float) -> dict | None:
    now = _now_iso()
    with get_conn() as conn:
        conn.execute('''
            UPDATE subscriptions
            SET status = ?, plan = ?, amount = ?, updated_at = ?
            WHERE user_id = ?
        ''', (status, plan, amount, now, user_id))
        conn.commit()
    return get_subscription(user_id)

# --- Settings Logic ---
def get_setting(key: str, default: str = '') -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row['value'] if row else default

def save_setting(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute('''
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        ''', (key, value))
        conn.commit()

def get_settings() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM settings").fetchall()
        return {r['key']: r['value'] for r in rows}

def get_active_company() -> str | None:
    value = get_setting('active_company', '')
    return value if value else None

def set_active_company(company_key: str) -> None:
    save_setting('active_company', company_key)

# --- Brands Logic ---
def create_brand(key: str, name: str, color: str = None, description: str = None, industry: str = None, website: str = None, status: str = 'active', logo_url: str = None, ai_prompt: str = None) -> dict:
    now = _now_iso()
    with get_conn() as conn:
        conn.execute('''
            INSERT INTO brands (key, name, color, description, industry, website, status, logo_url, ai_prompt, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (key, name, color or '#7b6ef6', description, industry, website, status, logo_url, ai_prompt, now, now))
        conn.commit()
    return get_brand(key)

def update_brand(key: str, name: str = None, color: str = None, description: str = None, industry: str = None, website: str = None, status: str = None, logo_url: str = None, ai_prompt: str = None) -> dict | None:
    fields = []
    params = []
    if name is not None:
        fields.append('name = ?')
        params.append(name)
    if color is not None:
        fields.append('color = ?')
        params.append(color)
    if description is not None:
        fields.append('description = ?')
        params.append(description)
    if industry is not None:
        fields.append('industry = ?')
        params.append(industry)
    if website is not None:
        fields.append('website = ?')
        params.append(website)
    if status is not None:
        fields.append('status = ?')
        params.append(status)
    if logo_url is not None:
        fields.append('logo_url = ?')
        params.append(logo_url)
    if ai_prompt is not None:
        fields.append('ai_prompt = ?')
        params.append(ai_prompt)
    if not fields:
        return get_brand(key)

    fields.append('updated_at = ?')
    params.append(_now_iso())
    params.append(key)

    with get_conn() as conn:
        conn.execute(f'UPDATE brands SET {", ".join(fields)} WHERE key = ?', tuple(params))
        conn.commit()
    return get_brand(key)

def delete_brand(key: str) -> None:
    with get_conn() as conn:
        conn.execute('DELETE FROM notifications WHERE payload = ?', (key,))
        conn.execute('DELETE FROM reports WHERE brand_key = ?', (key,))
        conn.execute('DELETE FROM campaigns WHERE brand_key = ?', (key,))
        conn.execute('DELETE FROM queries WHERE brand_key = ?', (key,))
        conn.execute('DELETE FROM chat_messages WHERE session_id IN (SELECT id FROM chat_sessions WHERE brand_key = ?)', (key,))
        conn.execute('DELETE FROM chat_sessions WHERE brand_key = ?', (key,))
        
        # Cascades documents and vectors
        doc_ids = [row['id'] for row in conn.execute('SELECT id FROM documents WHERE brand_key = ?', (key,)).fetchall()]
        for doc_id in doc_ids:
            conn.execute('DELETE FROM vectors WHERE document_id = ?', (doc_id,))
        conn.execute('DELETE FROM documents WHERE brand_key = ?', (key,))
        conn.execute('DELETE FROM brands WHERE key = ?', (key,))
        conn.commit()

def get_brand(key: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM brands WHERE key = ?', (key,)).fetchone()
        return _row_to_dict(row)

def get_brands() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute('SELECT * FROM brands ORDER BY name').fetchall()
        brands = [_row_to_dict(row) for row in rows]
        for brand in brands:
            stats = conn.execute('''
                SELECT
                    (SELECT COUNT(*) FROM documents WHERE brand_key = b.key) AS files,
                    (SELECT COUNT(*) FROM queries WHERE brand_key = b.key) AS queries,
                    COALESCE((SELECT SUM(chunk_index + 1) FROM vectors WHERE document_id IN (SELECT id FROM documents WHERE brand_key = b.key)), 0) AS chunks,
                    COALESCE((SELECT SUM(LENGTH(chunk_text)) FROM vectors WHERE document_id IN (SELECT id FROM documents WHERE brand_key = b.key)), 0) AS storage,
                    MAX(d.uploaded_at) AS last_upload
                FROM brands b
                LEFT JOIN documents d ON d.brand_key = b.key
                WHERE b.key = ?
            ''', (brand['key'],)).fetchone()
            
            brand['files'] = stats['files'] if stats else 0
            brand['queries'] = stats['queries'] if stats else 0
            brand['docs'] = stats['files'] if stats else 0
            brand['content'] = stats['files'] if stats else 0
            brand['chunks'] = stats['chunks'] if stats else 0
            brand['storage'] = stats['storage'] if stats else 0
            brand['last_upload'] = stats['last_upload'] or '' if stats else ''
            brand['status'] = brand.get('status') or 'active'
            brand['description'] = brand.get('description') or ''
            brand['industry'] = brand.get('industry') or ''
            brand['website'] = brand.get('website') or ''
            brand['logo_url'] = brand.get('logo_url') or ''
            brand['ai_prompt'] = brand.get('ai_prompt') or ''
            brand['updated_at'] = brand.get('updated_at') or brand.get('created_at')
    return brands

# --- Documents & Chunks RAG storage ---
def create_document(brand_key: str, filename: str, content: str, size: int, file_type: str, folder: str = 'uploads', status: str = 'indexed') -> dict:
    document_id = str(uuid4())
    now = _now_iso()
    with get_conn() as conn:
        conn.execute('''
            INSERT INTO documents (id, brand_key, title, filename, content, size, type, folder, status, uploaded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (document_id, brand_key, filename, filename, content, size, file_type, folder, status, now))
        conn.commit()
    create_notification('file_uploaded', f'Uploaded {filename} for brand {brand_key}', json.dumps({'brand': brand_key, 'filename': filename}))
    return get_document(document_id)

def store_chunk_vector(document_id: str, chunk_index: int, chunk_text: str, embedding_vector: list[float]) -> str:
    vec_id = str(uuid4())
    now = _now_iso()
    with get_conn() as conn:
        conn.execute('''
            INSERT INTO vectors (id, document_id, chunk_index, chunk_text, embedding, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (vec_id, document_id, chunk_index, chunk_text, json.dumps(embedding_vector), now))
        conn.commit()
    return vec_id

def rename_document(document_id: str, new_title: str) -> dict | None:
    with get_conn() as conn:
        conn.execute('UPDATE documents SET title = ?, filename = ? WHERE id = ?', (new_title, new_title, document_id))
        conn.commit()
    return get_document(document_id)


def delete_document(document_id: str) -> None:
    with get_conn() as conn:
        conn.execute('DELETE FROM vectors WHERE document_id = ?', (document_id,))
        conn.execute('DELETE FROM documents WHERE id = ?', (document_id,))
        conn.commit()


def get_document(document_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM documents WHERE id = ?', (document_id,)).fetchone()
        return _row_to_dict(row)

def get_uploaded_files(brand_key: str | None = None) -> list[dict]:
    with get_conn() as conn:
        if brand_key:
            rows = conn.execute('SELECT * FROM documents WHERE brand_key = ? ORDER BY uploaded_at DESC', (brand_key,)).fetchall()
        else:
            rows = conn.execute('SELECT * FROM documents ORDER BY uploaded_at DESC').fetchall()
        return [_row_to_dict(row) for row in rows]


def update_document_status(document_id: str, status: str) -> None:
    """Update the indexing status of a document."""
    with get_conn() as conn:
        conn.execute('UPDATE documents SET status = ? WHERE id = ?', (status, document_id))
        conn.commit()

# --- Vector Retrieval Helpers ---
def get_brand_chunks(brand_key: str) -> list[dict]:
    """Get ALL chunks for a brand (used for background/sync operations only).
    For retrieval, use get_brand_chunks_topk() instead."""
    with get_conn() as conn:
        rows = conn.execute('''
            SELECT v.*, d.title as doc_title, d.brand_key
            FROM vectors v
            JOIN documents d ON v.document_id = d.id
            WHERE d.brand_key = ?
        ''', (brand_key,)).fetchall()
        return [_row_to_dict(row) for row in rows]


def get_chunk_count(brand_key: str) -> int:
    """Get total chunk count for a brand (cheap count query, no full scan)."""
    with get_conn() as conn:
        row = conn.execute('''
            SELECT COUNT(*) as cnt FROM vectors v
            JOIN documents d ON v.document_id = d.id
            WHERE d.brand_key = ?
        ''', (brand_key,)).fetchone()
        return row['cnt'] if row else 0


def get_brand_chunks_topk(brand_key: str, query_embedding: list[float], top_k: int = 20) -> list[dict]:
    """Retrieve only TOP-K chunks for a brand by embedding similarity.
    Two-phase: fetch brand chunks (indexed), score, sort, return top K."""
    import json, math, sys, time as _time
    start = _time.time()

    chunks = get_brand_chunks(brand_key)
    fetch_elapsed = _time.time() - start
    print(f"[DB] get_brand_chunks_topk: fetched {len(chunks)} chunks for '{brand_key}' in {fetch_elapsed:.3f}s"); sys.stdout.flush()

    if not chunks:
        return []

    scored = []
    for chunk in chunks:
        try:
            raw = chunk.get('embedding')
            if not raw:
                continue
            vec = json.loads(raw) if isinstance(raw, str) else raw
            if not vec or len(vec) == 0:
                continue
            dot = sum(a * b for a, b in zip(query_embedding, vec))
            nq = math.sqrt(sum(a * a for a in query_embedding))
            nc = math.sqrt(sum(a * a for a in vec))
            if nq == 0 or nc == 0:
                continue
            score = dot / (nq * nc)
            scored.append({
                'chunk_text': chunk.get('chunk_text', ''),
                'doc_title': chunk.get('doc_title', 'document'),
                'brand_key': chunk.get('brand_key', brand_key),
                'score': score,
                'embedding': vec,
            })
        except Exception:
            continue

    scored.sort(key=lambda x: x['score'], reverse=True)
    top_results = scored[:top_k]
    elapsed = _time.time() - start
    print(f"[DB] get_brand_chunks_topk: scored {len(scored)}, returning top {len(top_results)} in {elapsed:.3f}s"); sys.stdout.flush()
    return top_results


def get_brand_chunks_keyword(brand_key: str, query_text: str, top_k: int = 20) -> list[dict]:
    """Retrieve top chunks for a brand by SQL LIKE keyword match on chunk_text.
    
    If brand_key is "ALL", searches across all brands. Otherwise, searches specific brand.
    """
    import time as _time
    start = _time.time()
    
    # Split query into words for keyword matching, filtering out short words
    words = [w.strip() for w in query_text.replace("'", "").split() if len(w.strip()) > 2]
    if not words:
        words = [query_text.strip()]
        
    conditions = []
    params = []
    for w in words[:4]:  # limit to 4 terms to keep it fast
        conditions.append("v.chunk_text LIKE ?")
        params.append(f"%{w}%")
        
    if not conditions:
        return []
    
    # Handle cross-brand queries
    if brand_key == "ALL":
        # Query across all brands
        sql = f"""
            SELECT v.*, d.title as doc_title, d.brand_key
            FROM vectors v
            JOIN documents d ON v.document_id = d.id
            WHERE ({" OR ".join(conditions)})
            LIMIT {top_k}
        """
    else:
        # Query specific brand
        sql = f"""
            SELECT v.*, d.title as doc_title, d.brand_key
            FROM vectors v
            JOIN documents d ON v.document_id = d.id
            WHERE d.brand_key = ? AND ({" OR ".join(conditions)})
            LIMIT {top_k}
        """
        params = [brand_key] + params
    
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        results = []
        for r in rows:
            dict_row = _row_to_dict(r)
            raw = dict_row.get('embedding')
            vec = json.loads(raw) if isinstance(raw, str) else raw
            # Give keyword hits a constant default score
            results.append({
                'chunk_text': dict_row.get('chunk_text', ''),
                'doc_title': dict_row.get('doc_title', 'document'),
                'brand_key': dict_row.get('brand_key', brand_key),
                'score': 0.5, # Base score for keyword matching
                'embedding': vec,
            })
        print(f"[DB] get_brand_chunks_keyword: matched {len(results)} chunks for '{brand_key}' in {_time.time() - start:.3f}s")
        return results


# --- Conversations & Messages ---
def create_conversation(user_id: str, brand_key: str, title: str) -> dict:
    conv_id = str(uuid4())
    now = _now_iso()
    with get_conn() as conn:
        conn.execute('''
            INSERT INTO conversations (id, user_id, brand_key, title, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (conv_id, user_id, brand_key, title, now))
        conn.commit()
    record_metric('conversation_created', 1.0, brand_key)
    return get_conversation(conv_id)


def create_chat_session(user_id: str, brand_key: str, title: str) -> dict:
    session_id = str(uuid4())
    now = _now_iso()
    # For backward compatibility, we store brand_id as brand_key for now.
    brand_id = brand_key

    def _insert() -> None:
        with get_conn() as conn:
            conn.execute('''
                INSERT INTO chat_sessions (
                    id, user_id, brand_key, brand_id, title, created_at, updated_at, is_pinned, is_archived
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)
            ''', (session_id, user_id, brand_key, brand_id, title, now, now))
            conn.commit()

    try:
        _insert()
    except sqlite3.OperationalError as e:
        # Runtime guard for older DBs missing updated_at.
        if 'chat_sessions' in str(e) and 'updated_at' in str(e):
            with get_conn() as conn:
                cursor = conn.cursor()
                try:
                    if not _has_column(cursor, 'chat_sessions', 'updated_at'):
                        # SQLite requires constant defaults in older versions; use NULLable column and backfill with now.
                        cursor.execute('ALTER TABLE chat_sessions ADD COLUMN updated_at TEXT')
                        cursor.execute('UPDATE chat_sessions SET updated_at = ? WHERE updated_at IS NULL', (now,))
                        conn.commit()
                        conn.commit()
                except Exception as e2:
                    raise sqlite3.OperationalError(f"Failed to migrate chat_sessions.updated_at: {e2}")
            # Retry once
            _insert()
        else:
            raise

    return get_chat_session(session_id)




def get_chat_session(session_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM chat_sessions WHERE id = ?', (session_id,)).fetchone()
        return _row_to_dict(row)


def get_chat_sessions(user_id: str, brand_key: str | None = None) -> list[dict]:
    with get_conn() as conn:
        if brand_key:
            rows = conn.execute('SELECT * FROM chat_sessions WHERE user_id = ? AND brand_key = ? ORDER BY created_at DESC', (user_id, brand_key)).fetchall()
        else:
            rows = conn.execute('SELECT * FROM chat_sessions WHERE user_id = ? ORDER BY created_at DESC', (user_id,)).fetchall()
        return [_row_to_dict(row) for row in rows]


def rename_chat_session(session_id: str, title: str) -> dict | None:
    now = _now_iso()
    with get_conn() as conn:
        conn.execute('UPDATE chat_sessions SET title = ?, updated_at = ? WHERE id = ?', (title, now, session_id))
        conn.commit()
    return get_chat_session(session_id)


def set_chat_session_pin_archive(session_id: str, *, is_pinned: bool | None = None, is_archived: bool | None = None) -> dict | None:
    now = _now_iso()
    with get_conn() as conn:
        current = conn.execute('SELECT is_pinned, is_archived FROM chat_sessions WHERE id = ?', (session_id,)).fetchone()
        if not current:
            return None

        next_pinned = current['is_pinned']
        next_archived = current['is_archived']
        if is_pinned is not None:
            next_pinned = 1 if is_pinned else 0
        if is_archived is not None:
            next_archived = 1 if is_archived else 0

        conn.execute(
            'UPDATE chat_sessions SET is_pinned = ?, is_archived = ?, updated_at = ? WHERE id = ?',
            (next_pinned, next_archived, now, session_id),
        )
        conn.commit()
    return get_chat_session(session_id)



def save_chat_message(
    session_id: str,
    role: str,
    question: str | None = None,
    answer: str | None = None,
    retrieved_documents: str | None = None,
    response_time: float | None = None,
    sources: str | None = None,
    attachments: str | None = None,
) -> dict:
    message_id = str(uuid4())
    now = _now_iso()

    # Backward compatibility:
    # - if sources not provided, use retrieved_documents (older pipeline)
    # - if attachments not provided, store empty array
    sources_v = sources if sources is not None else (retrieved_documents or '[]')
    attachments_v = attachments if attachments is not None else '[]'
    retrieved_documents_v = retrieved_documents or '[]'

    with get_conn() as conn:
        conn.execute('''
            INSERT INTO chat_messages (
                id, session_id, role, question, answer,
                sources, attachments, retrieved_documents,
                response_time, timestamp
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            message_id,
            session_id,
            role,
            question,
            answer,
            sources_v,
            attachments_v,
            retrieved_documents_v,
            response_time,
            now,
        ))
        conn.commit()

    return {
        'id': message_id,
        'session_id': session_id,
        'role': role,
        'question': question,
        'answer': answer,
        'sources': sources_v,
        'attachments': attachments_v,
        'retrieved_documents': retrieved_documents_v,
        'response_time': response_time,
        'timestamp': now,
    }



def get_chat_messages(session_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute('SELECT * FROM chat_messages WHERE session_id = ? ORDER BY timestamp ASC', (session_id,)).fetchall()
        return [_row_to_dict(row) for row in rows]


def delete_chat_session(session_id: str) -> None:
    with get_conn() as conn:
        conn.execute('DELETE FROM chat_messages WHERE session_id = ?', (session_id,))
        conn.execute('DELETE FROM chat_sessions WHERE id = ?', (session_id,))
        conn.commit()

def get_conversations(user_id: str, brand_key: str = None) -> list[dict]:
    with get_conn() as conn:
        if brand_key:
            rows = conn.execute('''
                SELECT * FROM conversations
                WHERE user_id = ? AND brand_key = ?
                ORDER BY created_at DESC
            ''', (user_id, brand_key)).fetchall()
        else:
            rows = conn.execute('''
                SELECT * FROM conversations
                WHERE user_id = ?
                ORDER BY created_at DESC
            ''', (user_id,)).fetchall()
        return [_row_to_dict(row) for row in rows]

def get_conversation(conv_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM conversations WHERE id = ?', (conv_id,)).fetchone()
        return _row_to_dict(row)

def delete_conversation(conv_id: str) -> None:
    with get_conn() as conn:
        conn.execute('DELETE FROM messages WHERE conversation_id = ?', (conv_id,))
        conn.execute('DELETE FROM conversations WHERE id = ?', (conv_id,))
        conn.commit()

def create_message(conversation_id: str, sender: str, text: str, inferred: int = 0, source_docs: str = '[]') -> dict:
    msg_id = str(uuid4())
    now = _now_iso()
    with get_conn() as conn:
        conn.execute('''
            INSERT INTO messages (id, conversation_id, sender, text, inferred, source_docs, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (msg_id, conversation_id, sender, text, inferred, source_docs, now))
        conn.commit()
    
    # Increment metrics
    if sender == 'ai':
        # Get brand key from conversation
        with get_conn() as conn2:
            conv = conn2.execute('SELECT brand_key FROM conversations WHERE id = ?', (conversation_id,)).fetchone()
            brand_key = conv['brand_key'] if conv else None
        record_metric('message_processed', 1.0, brand_key)
        
    return {'id': msg_id, 'conversation_id': conversation_id, 'sender': sender, 'text': text, 'inferred': inferred, 'source_docs': source_docs, 'created_at': now}

def get_messages(conversation_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute('''
            SELECT * FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC
        ''', (conversation_id,)).fetchall()
        return [_row_to_dict(row) for row in rows]

# --- Analytics Tracker ---
def record_metric(metric_type: str, metric_value: float, brand_key: str = None) -> None:
    timestamp = datetime.utcnow().strftime('%Y-%m-%d')
    with get_conn() as conn:
        # Check if daily metric exists for type/brand to accumulate, otherwise insert
        row = conn.execute('''
            SELECT id, metric_value FROM analytics
            WHERE metric_type = ? AND brand_key = ? AND timestamp = ?
        ''', (metric_type, brand_key, timestamp)).fetchone()
        
        if row:
            conn.execute('''
                UPDATE analytics
                SET metric_value = metric_value + ?
                WHERE id = ?
            ''', (metric_value, row['id']))
        else:
            conn.execute('''
                INSERT INTO analytics (id, metric_type, metric_value, brand_key, timestamp)
                VALUES (?, ?, ?, ?, ?)
            ''', (str(uuid4()), metric_type, metric_value, brand_key, timestamp))
        conn.commit()

def get_analytics_summary() -> dict:
    with get_conn() as conn:
        # User growth chart
        user_rows = conn.execute('''
            SELECT timestamp, SUM(metric_value) as val
            FROM analytics
            WHERE metric_type = 'user_signup'
            GROUP BY timestamp
            ORDER BY timestamp ASC
        ''').fetchall()
        
        # Conversations trend
        conv_rows = conn.execute('''
            SELECT timestamp, SUM(metric_value) as val
            FROM analytics
            WHERE metric_type = 'conversation_created'
            GROUP BY timestamp
            ORDER BY timestamp ASC
        ''').fetchall()

        # AI Message Volume
        msg_rows = conn.execute('''
            SELECT timestamp, SUM(metric_value) as val
            FROM analytics
            WHERE metric_type = 'message_processed'
            GROUP BY timestamp
            ORDER BY timestamp ASC
        ''').fetchall()

        # Revenue MRR
        revenue_rows = conn.execute('''
            SELECT timestamp, SUM(metric_value) as val
            FROM analytics
            WHERE metric_type = 'revenue'
            GROUP BY timestamp
            ORDER BY timestamp ASC
        ''').fetchall()

        # Brand Performance Share (Pie Chart)
        brand_rows = conn.execute('''
            SELECT brand_key, SUM(metric_value) as val
            FROM analytics
            WHERE metric_type = 'query' AND brand_key IS NOT NULL
            GROUP BY brand_key
        ''').fetchall()

        # Top Active Users (using static mock/real users based on conversations/messages counts)
        user_list = [
            {'name': 'Admin User', 'email': 'admin@digitz.co', 'queries': 842, 'role': 'Administrator'},
            {'name': 'Brand Strategist', 'email': 'marketing@digitz.co', 'queries': 512, 'role': 'User'},
            {'name': 'Sales Lead', 'email': 'sales@digitz.co', 'queries': 230, 'role': 'User'},
            {'name': 'Data Specialist', 'email': 'ops@digitz.co', 'queries': 184, 'role': 'User'},
        ]

    return {
        'user_growth': [{'date': r['timestamp'], 'users': r['val']} for r in user_rows],
        'conversations_trend': [{'date': r['timestamp'], 'conversations': r['val']} for r in conv_rows],
        'ai_usage': [{'date': r['timestamp'], 'messages': r['val']} for r in msg_rows],
        'revenue': [{'date': r['timestamp'], 'mrr': r['val']} for r in revenue_rows],
        'brand_performance': [{'brand': r['brand_key'], 'queries': r['val']} for r in brand_rows],
        'top_users': user_list
    }

# --- Legacy Queries Logic (Preserving API signatures) ---
def record_query(query_text: str, brand_key: str | None, mode: str | None, answer_excerpt: str, status: str = 'done', response_time: float | None = None, similarity_score: float | None = None, retrieved_chunks: int | None = None, session_id: str | None = None) -> dict:
    query_id = str(uuid4())
    now = _now_iso()

    # Normalize nullable numeric fields so DB inserts are stable across older schemas.
    response_time_v = float(response_time) if response_time is not None else None
    similarity_score_v = float(similarity_score) if similarity_score is not None else None
    retrieved_chunks_v = int(retrieved_chunks) if retrieved_chunks is not None else None

    with get_conn() as conn:
        conn.execute('''
            INSERT INTO queries (id, query_text, brand_key, mode, status, answer_excerpt, response_time, similarity_score, retrieved_chunks, session_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (query_id, query_text, brand_key, mode or 'Creative', status, answer_excerpt, response_time_v, similarity_score_v, retrieved_chunks_v, session_id, now))
        conn.commit()

    create_notification('query_completed', f'AI query executed for brand {brand_key}', json.dumps({'brand': brand_key, 'query': query_text}))
    record_metric('query', 1.0, brand_key)
    return get_query(query_id)


def get_query(query_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM queries WHERE id = ?', (query_id,)).fetchone()
        return _row_to_dict(row)

def get_recent_queries(limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute('SELECT * FROM queries ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
        return [_row_to_dict(row) for row in rows]

def get_upload_summary() -> dict:
    with get_conn() as conn:
        total_docs = conn.execute('SELECT COUNT(*) AS count FROM documents').fetchone()['count']
        
        # Get count of total chunks across vectors table
        chunks_count = conn.execute('SELECT COUNT(*) AS count FROM vectors').fetchone()['count']
        
        total_queries = conn.execute('SELECT COUNT(*) AS count FROM queries').fetchone()['count']
        total_reports = conn.execute('SELECT COUNT(*) AS count FROM reports').fetchone()['count']
        total_campaigns = conn.execute('SELECT COUNT(*) AS count FROM campaigns').fetchone()['count']
        
        # Get counts of total users and revenue
        total_users = conn.execute('SELECT COUNT(*) AS count FROM users').fetchone()['count']
        active_users = total_users # fallback simple
        
        # Sum revenue for active subscriptions
        rev_row = conn.execute("SELECT SUM(amount) AS sum FROM subscriptions WHERE status = 'active'").fetchone()
        mrr = rev_row['sum'] if rev_row and rev_row['sum'] else 199.00
        
        active_brands = conn.execute('SELECT COUNT(*) AS count FROM brands WHERE status = \'active\'').fetchone()['count']
        brands_data = get_brands()
        recent_uploads = [
            {
                'id': row['id'],
                'title': row['title'],
                'brand': row['brand_key'],
                'snippet': (row['content'][:120] + ('...' if len(row['content']) > 120 else '')),
                'uploaded_at': row['uploaded_at'],
            }
            for row in get_uploaded_files()[:5]
        ]
        query_history = [
            {
                'query': row['query_text'],
                'brand': row['brand_key'] or 'unknown',
                'mode': row['mode'],
                'timestamp': row['created_at'],
                'status': row['status'],
                'answer_excerpt': row['answer_excerpt'],
            }
            for row in get_recent_queries(8)
        ]
    return {
        'total_docs': total_docs,
        'chunks_count': chunks_count,
        'total_queries': total_queries,
        'total_reports': total_reports,
        'total_campaigns': total_campaigns,
        'total_users': total_users,
        'active_users': active_users,
        'monthly_revenue': mrr,
        'total_active_brands': active_brands,
        'brands': brands_data,
        'recent_uploads': recent_uploads,
        'query_history': query_history,
        'api_usage': total_queries + chunks_count # fallback metric
    }

def search_all(query_text: str, top_k: int = 20, brand_key: str | None = None) -> list[dict]:
    sql = '%{}%'.format(query_text)
    results = []
    with get_conn() as conn:
        if brand_key:
            rows = conn.execute('''
                SELECT title, content, brand_key FROM documents
                WHERE brand_key = ? AND (title LIKE ? OR content LIKE ?)
                ORDER BY uploaded_at DESC LIMIT ?
            ''', (brand_key, sql, sql, top_k)).fetchall()
        else:
            rows = conn.execute('''
                SELECT title, content, brand_key FROM documents
                WHERE title LIKE ? OR content LIKE ?
                ORDER BY uploaded_at DESC LIMIT ?
            ''', (sql, sql, top_k)).fetchall()
        for row in rows:
            results.append({
                'type': 'document',
                'title': row['title'],
                'subtitle': row['content'][:120] + ('...' if len(row['content']) > 120 else ''),
                'brand': row['brand_key'],
            })

        if brand_key:
            rows = conn.execute('''
                SELECT name, brand_key, objective FROM campaigns
                WHERE brand_key = ? AND (name LIKE ? OR objective LIKE ?)
                ORDER BY created_at DESC LIMIT ?
            ''', (brand_key, sql, sql, top_k)).fetchall()
        else:
            rows = conn.execute('''
                SELECT name, brand_key, objective FROM campaigns
                WHERE name LIKE ? OR objective LIKE ?
                ORDER BY created_at DESC LIMIT ?
            ''', (sql, sql, top_k)).fetchall()
        for row in rows:
            results.append({
                'type': 'campaign',
                'title': row['name'],
                'subtitle': row['objective'] or 'Campaign asset',
                'brand': row['brand_key'],
            })

        if brand_key:
            rows = conn.execute('''
                SELECT report_type, period, brand_key FROM reports
                WHERE brand_key = ? AND (report_type LIKE ? OR period LIKE ?)
                ORDER BY created_at DESC LIMIT ?
            ''', (brand_key, sql, sql, top_k)).fetchall()
        else:
            rows = conn.execute('''
                SELECT report_type, period, brand_key FROM reports
                WHERE report_type LIKE ? OR period LIKE ?
                ORDER BY created_at DESC LIMIT ?
            ''', (sql, sql, top_k)).fetchall()
        for row in rows:
            results.append({
                'type': 'report',
                'title': f"{row['report_type']} report",
                'subtitle': row['period'],
                'brand': row['brand_key'],
            })

        if brand_key:
            rows = conn.execute('''
                SELECT key AS title, name AS subtitle FROM brands
                WHERE key = ? AND (key LIKE ? OR name LIKE ?)
                ORDER BY name ASC LIMIT ?
            ''', (brand_key, sql, sql, top_k)).fetchall()
        else:
            rows = conn.execute('''
                SELECT key AS title, name AS subtitle FROM brands
                WHERE key LIKE ? OR name LIKE ?
                ORDER BY name ASC LIMIT ?
            ''', (sql, sql, top_k)).fetchall()
        for row in rows:
            results.append({
                'type': 'brand',
                'title': row['title'],
                'subtitle': row['subtitle'],
                'brand': row['title'],
            })

        if brand_key:
            rows = conn.execute('''
                SELECT query_text, mode, brand_key FROM queries
                WHERE brand_key = ? AND query_text LIKE ?
                ORDER BY created_at DESC LIMIT ?
            ''', (brand_key, sql, top_k)).fetchall()
        else:
            rows = conn.execute('''
                SELECT query_text, mode, brand_key FROM queries
                WHERE query_text LIKE ?
                ORDER BY created_at DESC LIMIT ?
            ''', (sql, top_k)).fetchall()
        for row in rows:
            results.append({
                'type': 'query',
                'title': row['query_text'],
                'subtitle': row['mode'],
                'brand': row['brand_key'] or 'unknown',
            })
    return results

# --- Notifications ---
def get_notifications(limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute('SELECT * FROM notifications ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
        return [_row_to_dict(row) for row in rows]

def create_notification(notification_type: str, message: str, payload: str | None = None) -> None:
    with get_conn() as conn:
        conn.execute('''
            INSERT INTO notifications (id, type, message, payload, read, created_at)
            VALUES (?, ?, ?, ?, 0, ?)
        ''', (str(uuid4()), notification_type, message, payload or '{}', _now_iso()))
        conn.commit()

def get_notification_counts() -> dict:
    with get_conn() as conn:
        count = conn.execute('SELECT COUNT(*) AS total FROM notifications WHERE read = 0').fetchone()['total']
        return {'unread': count}

def mark_notification_read(notification_id: str) -> None:
    with get_conn() as conn:
        conn.execute('UPDATE notifications SET read = 1 WHERE id = ?', (notification_id,))
        conn.commit()

def mark_all_notifications_read() -> None:
    with get_conn() as conn:
        conn.execute('UPDATE notifications SET read = 1 WHERE read = 0')
        conn.commit()

# --- Reports ---
def create_report(brand_key: str, report_type: str, period: str, file_name: str, status: str = 'generated') -> dict:
    report_id = str(uuid4())
    now = _now_iso()
    with get_conn() as conn:
        conn.execute('''
            INSERT INTO reports (id, brand_key, report_type, period, file_name, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (report_id, brand_key, report_type, period, file_name, status, now))
        conn.commit()
    create_notification('report_generated', f'Report generated for brand {brand_key}', json.dumps({'brand': brand_key, 'report': report_type}))
    return get_report(report_id)

def get_report(report_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM reports WHERE id = ?', (report_id,)).fetchone()
        return _row_to_dict(row)

def get_reports(limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute('SELECT * FROM reports ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
        return [_row_to_dict(row) for row in rows]

# --- Campaigns ---
def add_campaign(name: str, brand_key: str, objective: str, target_audience: str, budget: float, timeline: str, status: str = 'Draft') -> dict:
    campaign_id = str(uuid4())
    now = _now_iso()
    with get_conn() as conn:
        conn.execute('''
            INSERT INTO campaigns (id, name, brand_key, objective, target_audience, budget, timeline, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (campaign_id, name, brand_key, objective, target_audience, budget, timeline, status, now))
        conn.commit()
    create_notification('campaign_created', f'Campaign created for brand {brand_key}', json.dumps({'name': name, 'brand': brand_key}))
    return get_campaign(campaign_id)

def get_campaign(campaign_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM campaigns WHERE id = ?', (campaign_id,)).fetchone()
        return _row_to_dict(row)

def get_campaigns(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute('SELECT * FROM campaigns ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
        return [_row_to_dict(row) for row in rows]
