import os
import threading
import uuid

from flask import Flask, jsonify, request, session
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

try:
    from .config import FRONTEND_ORIGIN
    from .db import (
        init_db, create_user, get_user_by_email, get_user,
        create_project, update_project, get_project, list_projects
    )
    from .services.pipeline import run_project
    from .services.map_layers import register_map_layer_routes
    from .services.aoi_analysis import register_aoi_routes
    from .services.stress_analysis import register_stress_routes
    from .services.environmental_watch import register_environmental_watch_routes
    from .services.environmental_watch_demo_route import (
        register_environmental_watch_demo_route
    )
except ImportError:
    from config import FRONTEND_ORIGIN
    from db import (
        init_db, create_user, get_user_by_email, get_user,
        create_project, update_project, get_project, list_projects
    )
    from services.pipeline import run_project
    from .services.map_layers import register_map_layer_routes
    from services.aoi_analysis import register_aoi_routes
    from services.stress_analysis import register_stress_routes
    from services.environmental_watch import (
        register_environmental_watch_routes,
    )
    from services.environmental_watch_demo_route import (
        register_environmental_watch_demo_route
    )

app = Flask(__name__)

register_aoi_routes(app)
register_stress_routes(app)
register_environmental_watch_routes(app)
register_environmental_watch_demo_route(app)
app.config.update(
    SECRET_KEY=os.getenv("FLASK_SECRET_KEY", "dev-only-change-this"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
)

CORS(app, origins=[FRONTEND_ORIGIN], supports_credentials=True)
init_db()
register_map_layer_routes(app)
from .db import seed_test_user
seed_test_user()

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

@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "tshaai-api"})

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
@login_required
def start_project(user):
    body = request.get_json(silent=True) or {}
    project_name = (
        str(body.get("projectName", "Untitled Project")).strip()
        or "Untitled Project"
    )

    project_id = str(uuid.uuid4())
    create_project(project_id, user["id"], project_name, body)
    update_project(
        project_id,
        status="queued",
        stage="Queued for analysis",
        progress=0,
    )

    thread = threading.Thread(
        target=run_project,
        args=(project_id, body),
        daemon=True,
    )
    thread.start()

    return jsonify({
        "projectId": project_id,
        "status": "queued",
        "stage": "Queued for analysis",
        "progress": 0,
    }), 202

@app.post("/api/projects/analyze")
@login_required
def analyze_compat(user):
    body = request.get_json(silent=True) or {}

    project_name = (
        str(body.get("projectName", "Untitled Project")).strip()
        or "Untitled Project"
    )

    project_id = str(uuid.uuid4())

    create_project(
        project_id,
        user["id"],
        project_name,
        body,
    )

    update_project(
        project_id,
        status="queued",
        stage="Queued for analysis",
        progress=0,
    )

    thread = threading.Thread(
        target=run_project,
        args=(project_id, body),
        daemon=True,
    )
    thread.start()

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

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
