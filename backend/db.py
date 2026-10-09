import sqlite3
from .config import DATABASE_PATH

def connect():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = connect()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        organisation TEXT NOT NULL,
        name TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        project_name TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',
        stage TEXT NOT NULL DEFAULT 'queued',
        progress INTEGER NOT NULL DEFAULT 0,
        result_json TEXT,
        error TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    """)
    conn.commit()
    conn.close()

def create_user(email, password_hash, organisation, name=None):
    conn = connect()
    try:
        cur = conn.execute(
            "INSERT INTO users(email,password_hash,organisation,name) VALUES(?,?,?,?)",
            (email, password_hash, organisation, name),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()

def get_user_by_email(email):
    conn = connect()
    row = conn.execute(
        "SELECT id,email,password_hash,organisation,name,created_at FROM users WHERE email=?",
        (email,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def get_user(user_id):
    conn = connect()
    row = conn.execute(
        "SELECT id,email,organisation,name,created_at FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def create_project(project_id, user_id, project_name, payload):
    import json
    conn = connect()
    conn.execute(
        "INSERT INTO projects(id,user_id,project_name,payload_json) VALUES(?,?,?,?)",
        (project_id, user_id, project_name, json.dumps(payload)),
    )
    conn.commit()
    conn.close()

def update_project(project_id, **fields):
    import json
    allowed = {"status", "stage", "progress", "result_json", "error"}
    updates, values = [], []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "result_json" and not isinstance(value, str):
            value = json.dumps(value)
        updates.append(f"{key}=?")
        values.append(value)
    if not updates:
        return
    updates.append("updated_at=CURRENT_TIMESTAMP")
    values.append(project_id)
    conn = connect()
    conn.execute(f"UPDATE projects SET {', '.join(updates)} WHERE id=?", values)
    conn.commit()
    conn.close()

def get_project(project_id, user_id):
    import json
    conn = connect()
    row = conn.execute(
        "SELECT * FROM projects WHERE id=? AND user_id=?",
        (project_id, user_id),
    ).fetchone()
    conn.close()
    if not row:
        return None
    item = dict(row)
    item["payload"] = json.loads(item.pop("payload_json"))
    if item.get("result_json"):
        item["result"] = json.loads(item.pop("result_json"))
    else:
        item.pop("result_json", None)
    return item

def list_projects(user_id):
    conn = connect()
    rows = conn.execute(
        """SELECT id,project_name,status,stage,progress,error,created_at,updated_at
           FROM projects WHERE user_id=? ORDER BY created_at DESC""",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
def seed_test_user():
    from werkzeug.security import generate_password_hash

    email = "test@shuhul.local"
    password = "ShuhulTest123!"
    organisation = "Shuhul Development"
    name = "Shuhul Test User"

    conn = connect()

    existing = conn.execute(
        "SELECT id FROM users WHERE email=?",
        (email,)
    ).fetchone()

    if existing:
        conn.close()
        return existing["id"]

    cur = conn.execute(
        """
        INSERT INTO users
        (email, password_hash, organisation, name)
        VALUES (?, ?, ?, ?)
        """,
        (
            email,
            generate_password_hash(password),
            organisation,
            name,
        ),
    )

    conn.commit()
    user_id = cur.lastrowid
    conn.close()

    return user_id