"""
Synrix Agent Runtime — Dashboard Application
Serves the Lovable React dashboard as static files.
"""

import os
from pathlib import Path
from flask import Flask, send_from_directory
from flask_cors import CORS


def create_app():
    """Create and configure the Flask dashboard application."""
    static_dir = Path(__file__).parent / "static"
    app = Flask(__name__, static_folder=str(static_dir))
    CORS(app, origins=["http://localhost:7842", "http://127.0.0.1:7842",
                        "http://localhost:8000", "http://127.0.0.1:8000"])

    from synrix_runtime.dashboard.api_routes import api
    app.register_blueprint(api)

    @app.route("/assets/<path:filename>")
    def assets(filename):
        return send_from_directory(str(static_dir / "assets"), filename)

    @app.route("/images/<path:filename>")
    def images(filename):
        return send_from_directory(str(static_dir / "images"), filename)

    @app.route("/downloads/<path:filename>")
    def downloads(filename):
        return send_from_directory(str(static_dir / "downloads"), filename)

    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(str(static_dir), "favicon.ico")

    # SPA catch-all: serve index.html for all non-API, non-asset routes
    # React Router handles client-side routing
    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_spa(path):
        # If the file exists in static, serve it
        file_path = static_dir / path
        if path and file_path.is_file():
            return send_from_directory(str(static_dir), path)
        # Otherwise serve index.html (React Router handles the route)
        return send_from_directory(str(static_dir), "index.html")

    return app


def run_dashboard(port=7842, debug=False):
    """Start the dashboard server."""
    app = create_app()
    print(f"[DASHBOARD] Starting on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True)


if __name__ == "__main__":
    run_dashboard()
