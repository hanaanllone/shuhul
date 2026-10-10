import threading
import time
import uuid
from collections import defaultdict, deque
from functools import wraps

from flask import Flask, jsonify, request, session
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

from .config import (
    FRONTEND_ORIGINS,
    INLINE_WORKER,
    IS_PRODUCTION,
    MAX_ACTIVE_PROJECTS_PER_USER,
    SECRET_KEY,
)
from .db import (
    init_db, create_user, get_user_by_email, get_user,
    create_project, get_project, list_projects, count_active_projects,
)
from .services.map_layers import register_map_layer_routes, build_project_corridors
from .services.aoi_analysis import register_aoi_routes
from .services.stress_analysis import register_stress_routes
from .services.environmental_watch import register_environmental_watch_routes
from .services.environmental_watch_demo_route import (
    register_environmental_watch_demo_route
)
from .services.watch_ingest import register_watch_routes

app = Flask(__name__)

# Keep keys in the order they were written, so map layers list as registered.
app.json.sort_keys = False

register_aoi_routes(app)
register_stress_routes(app)
register_environmental_watch_routes(app)
register_environmental_watch_demo_route(app)
register_watch_routes(app)
register_map_layer_routes(app)

app.config.update(
    SECRET_KEY=SECRET_KEY,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_PRODUCTION,
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)

CORS(app, origins=FRONTEND_ORIGINS, supports_credentials=True)
init_db()

# Everything under /api needs a signed-in user except these.
PUBLIC_PREFIXES = ("/api/health", "/api/auth/", "/api/tiles/")

# Sign-in attempts allowed per address and email inside the window.
LOGIN_ATTEMPTS = 10
LOGIN_WINDOW_SECONDS = 15 * 60
_login_attempts = defaultdict(deque)
_login_lock = threading.Lock()


def current_user():
    user_id = session.get("user_id")
    return get_user(user_id) if user_id else None

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"error": "authentication_required"}), 401
        return fn(user, *args, **kwargs)
    return wrapper

_worker_started = False
_worker_lock = threading.Lock()

def ensure_inline_worker():
    """
    Start the in-process worker on the first request. Starting it here,
    rather than at import, keeps it out of the reloader's parent process.
    """
    global _worker_started

    if _worker_started:
        return

    with _worker_lock:
        if _worker_started:
            return
        from .worker import work_forever
        threading.Thread(target=work_forever, name="shuhul-worker", daemon=True).start()
        _worker_started = True

@app.before_request
def require_session():
    if INLINE_WORKER:
        ensure_inline_worker()

    path = request.path
    if request.method == "OPTIONS" or not path.startswith("/api/"):
        return None
    if path.startswith(PUBLIC_PREFIXES):
        return None
    if not session.get("user_id"):
        return jsonify({"error": "authentication_required"}), 401
    return None

def too_many_attempts(email):
    """Record a sign-in attempt and say whether this caller is over the limit."""
    key = (request.remote_addr or "unknown", email)
    now = time.time()

    with _login_lock:
        attempts = _login_attempts[key]
        while attempts and now - attempts[0] > LOGIN_WINDOW_SECONDS:
            attempts.popleft()
        if len(attempts) >= LOGIN_ATTEMPTS:
            return True
        attempts.append(now)
        return False

@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "shuhul-api"})

@app.post("/api/auth/signup")
def signup():
    body = request.get_json(silent=True) or {}
    email = str(body.get("email", "")).strip().lower()
    password = str(body.get("password", ""))
    organisation = str(body.get("organisation", "")).strip()
    name = str(body.get("name", "")).strip() or None

    if not email or "@" not in email:
        return jsonify({"error": "A valid email is required."}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400
    if not organisation:
        return jsonify({"error": "Organisation is required."}), 400
    if get_user_by_email(email):
        return jsonify({"error": "An account with this email already exists."}), 409

    user_id = create_user(
        email,
        generate_password_hash(password),
        organisation,
        name,
    )
    session.clear()
    session["user_id"] = user_id

    return jsonify({"authenticated": True, "user": get_user(user_id)}), 201

@app.post("/api/auth/login")
def login():
    body = request.get_json(silent=True) or {}
    email = str(body.get("email", "")).strip().lower()
    password = str(body.get("password", ""))

    if too_many_attempts(email):
        return jsonify({
            "error": "Too many sign-in attempts. Please wait a few minutes."
        }), 429

    user = get_user_by_email(email)
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid email or password."}), 401

    session.clear()
    session["user_id"] = user["id"]

    public = {
        k: user[k]
        for k in ("id", "email", "organisation", "name", "created_at")
    }
    return jsonify({"authenticated": True, "user": public})

@app.get("/api/auth/session")
def session_info():
    user = current_user()
    if not user:
        return jsonify({"authenticated": False})
    return jsonify({"authenticated": True, "user": user})

@app.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify({"authenticated": False})

@app.get("/api/projects")
@login_required
def projects(user):
    return jsonify({"projects": list_projects(user["id"])})

@app.get("/api/projects/<project_id>")
@login_required
def project_detail(user, project_id):
    project = get_project(project_id, user["id"])
    if not project:
        return jsonify({"error": "Project not found."}), 404
    return jsonify(project)

@app.post("/api/projects")
@app.post("/api/projects/analyze")
@login_required
def start_project(user):
    """
    Queue a project for analysis. The worker picks it up from the
    database, so a queued project survives a restart.
    """
    body = request.get_json(silent=True) or {}
    project_name = (
        str(body.get("projectName", "Untitled Project")).strip()
        or "Untitled Project"
    )

    if count_active_projects(user["id"]) >= MAX_ACTIVE_PROJECTS_PER_USER:
        return jsonify({
            "error": (
                "You already have analyses running. "
                "Wait for one to finish before starting another."
            )
        }), 429

    project_id = str(uuid.uuid4())
    create_project(project_id, user["id"], project_name, body)

    return jsonify({
        "projectId": project_id,
        "status": "queued",
        "stage": "Queued for analysis",
        "progress": 0,
    }), 202

@app.get("/api/projects/<project_id>/status")
@login_required
def project_status(user, project_id):
    project = get_project(project_id, user["id"])
    if not project:
        return jsonify({"error": "Project not found."}), 404

    return jsonify({
        "projectId": project["id"],
        "status": project["status"],
        "stage": project["stage"],
        "progress": project["progress"],
        "error": project["error"],
        "result": project.get("result"),
    })


@app.get("/api/projects/<project_id>/corridors")
@login_required
def project_corridors(user, project_id):
    project = get_project(project_id, user["id"])
    if not project:
        return jsonify({"error": "Project not found."}), 404

    payload = project["payload"]
    width = float(request.args.get("width", payload.get("widthMeters", 20)))

    return jsonify(
        build_project_corridors(project_id, payload["constructionType"], width)
    )

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=not IS_PRODUCTION)
