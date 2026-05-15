"""audit_v2.standalone - a runnable, self-contained audit viewer.

Start with:
    OCTOPODA_API_KEY=sk-octopoda-... python -m synrix_runtime.audit_v2.standalone

Then open http://127.0.0.1:8765/ in a browser. The server:
  - mounts the audit_v2 router at /v1/audit_v2/*
  - serves a single-page vanilla-JS dashboard at /
  - is isolated from the main API (different port, different app)

This is NOT production. It's a demo artifact so we can visually verify
the audit data without wiring anything into the main dashboard.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def build_standalone_app():
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse

    from synrix_runtime.audit_v2.api import build_router

    app = FastAPI(title="audit_v2 standalone viewer")

    # Permissive CORS because this is a local demo. Production code
    # would scope origins tightly.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(build_router(), prefix="/v1/audit_v2")

    ui_dir = Path(__file__).parent / "ui"
    if ui_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(ui_dir)), name="static")

        @app.get("/")
        def index():
            index_path = ui_dir / "index.html"
            if index_path.exists():
                return FileResponse(str(index_path), media_type="text/html")
            return {"error": "UI not found at " + str(index_path)}
    else:
        @app.get("/")
        def no_ui():
            return {
                "status": "API online, no UI bundled",
                "endpoints": [
                    "/v1/audit_v2/events",
                    "/v1/audit_v2/events/{id}",
                    "/v1/audit_v2/events/{id}/context",
                    "/v1/audit_v2/verify",
                    "/v1/audit_v2/cost",
                    "/v1/audit_v2/export",
                ],
            }

    @app.get("/health")
    def health():
        return {"ok": True, "service": "audit_v2_standalone"}

    return app


def main():
    parser = argparse.ArgumentParser(description="audit_v2 standalone viewer")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765,
                        help="Port to bind (default: 8765)")
    parser.add_argument("--reload", action="store_true",
                        help="Enable auto-reload (dev only)")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print("uvicorn is required. Install: pip install uvicorn",
              file=sys.stderr)
        sys.exit(1)

    if not os.environ.get("DATABASE_URL"):
        print("WARN: DATABASE_URL not set. The API will not be able to read events.",
              file=sys.stderr)

    print(f"audit_v2 standalone viewer starting on http://{args.host}:{args.port}")
    print(f"  Open in browser: http://{args.host}:{args.port}/")
    uvicorn.run(
        "synrix_runtime.audit_v2.standalone:build_standalone_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
