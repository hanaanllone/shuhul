# Static Environmental Watch demo route
# Copy this file to Tshaai/backend/services/environmental_watch_demo_route.py
from pathlib import Path
import json

def register_environmental_watch_demo_route(app):
    from flask import jsonify
    demo_path = Path(__file__).resolve().parent / "environmental_watch_demo_analysis.json"

    @app.get("/api/environmental-watch/demo-analysis")
    def environmental_watch_demo_analysis():
        if not demo_path.exists():
            return jsonify({"error": "Demo analysis file not found."}), 404
        return jsonify(json.loads(demo_path.read_text(encoding="utf-8")))
