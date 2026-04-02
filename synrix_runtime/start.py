"""
Synrix Agent Runtime
====================
Start with: python start.py
            python start.py --demo
            python start.py --demo --no-browser
"""

import sys
import os
import time
import threading
import argparse
import webbrowser

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Load .env file if it exists (so users don't have to set env vars manually)
_env_file = os.path.join(_project_root, ".env")
if os.path.isfile(_env_file):
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                _key, _val = _key.strip(), _val.strip().strip('"').strip("'")
                if _key and _key not in os.environ:
                    os.environ[_key] = _val


STARTUP_BANNER = """
 +=======================================================+
 |          OCTOPODA AGENT RUNTIME v3.0.3                |
 |          Persistent Memory Kernel for AI Agents       |
 +=======================================================+
 |  Backend:            + {backend:<28s}|
 |  Data directory:     + {data_dir:<28s}|
 |  Connection:         + {connect_us:>8.1f}us                   |
 |  Daemon:             + Running                        |
 |  Dashboard:          + http://localhost:{dash_port:<14d}|
 |  Cloud API:          + http://localhost:{api_port:<14d}|
 |  API Docs:           + http://localhost:{api_port}/docs{docs_pad}|
 +=======================================================+
"""


def main():
    parser = argparse.ArgumentParser(description="Synrix Agent Runtime")
    parser.add_argument("--demo", action="store_true", help="Start the three-agent demo")
    parser.add_argument("--port", type=int, default=None, help="Dashboard port")
    parser.add_argument("--api-port", type=int, default=None, help="Cloud API port")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser")
    parser.add_argument("--no-api", action="store_true", help="Don't start cloud API server")
    args = parser.parse_args()

    # Load config
    from synrix_runtime.config import SynrixConfig
    config = SynrixConfig.from_env()

    if args.port:
        config.dashboard_port = args.port
    if args.api_port:
        config.api_port = args.api_port
    if args.no_api:
        config.api_enabled = False

    # Step 1: Connect to Synrix with real persistent backend
    start = time.perf_counter_ns()
    try:
        from synrix.agent_backend import get_synrix_backend
        backend_kwargs = config.get_backend_kwargs()
        backend = get_synrix_backend(**backend_kwargs)
        connect_us = (time.perf_counter_ns() - start) / 1000

        # Verify connection
        test_start = time.perf_counter_ns()
        backend.write("runtime:health_check", {"status": "ok", "timestamp": time.time()})
        verify_us = (time.perf_counter_ns() - test_start) / 1000
    except Exception as e:
        print(f"\n  [ERROR] Failed to connect to Synrix: {e}")
        print(f"  Check that Synrix is installed: pip install synrix")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    backend_type = backend.backend_type

    # Step 2: Start daemon (will use same config to get backend)
    from synrix_runtime.core.daemon import RuntimeDaemon
    daemon = RuntimeDaemon.get_instance()
    daemon.start()

    # Step 3: Print banner
    data_dir_display = config.data_dir
    if len(data_dir_display) > 28:
        data_dir_display = "..." + data_dir_display[-25:]

    # Calculate padding for docs URL
    docs_url_len = len(f"http://localhost:{config.api_port}/docs")
    docs_pad = " " * max(0, 28 - docs_url_len)

    print(STARTUP_BANNER.format(
        backend=backend_type.upper() + " (persistent)",
        data_dir=data_dir_display,
        connect_us=connect_us,
        dash_port=config.dashboard_port,
        api_port=config.api_port,
        docs_pad=docs_pad,
    ))

    # Step 4: Start dashboard in background thread
    _dash_error = []
    if config.dashboard_enabled:
        def start_dashboard():
            try:
                from synrix_runtime.dashboard.app import create_app
                app = create_app()
                app.run(host="0.0.0.0", port=config.dashboard_port, debug=False, threaded=True, use_reloader=False)
            except Exception as e:
                _dash_error.append(str(e))
                if "flask" in str(e).lower():
                    print(f"\n  [DASHBOARD] Flask not installed. Run: pip install octopoda[server]")
                else:
                    print(f"\n  [DASHBOARD ERROR] Failed to start: {e}")

        dash_thread = threading.Thread(target=start_dashboard, daemon=True)
        dash_thread.start()

    # Step 5: Start cloud API server
    _api_error = []
    if config.api_enabled:
        def start_api_server():
            try:
                from synrix_runtime.api.cloud_server import app as fastapi_app, init_cloud_server
                import uvicorn

                # Initialize with daemon reference
                init_cloud_server(daemon, config)

                uvicorn.run(
                    fastapi_app,
                    host=config.api_host,
                    port=config.api_port,
                    log_level=config.log_level.lower(),
                    access_log=False,
                )
            except ImportError:
                _api_error.append("FastAPI/uvicorn not installed")
                print(f"\n  [API] FastAPI/uvicorn not installed. Cloud API disabled.")
                print(f"  [API] Install with: pip install fastapi uvicorn")
            except Exception as e:
                _api_error.append(str(e))
                print(f"\n  [API ERROR] {e}")

        api_thread = threading.Thread(target=start_api_server, daemon=True)
        api_thread.start()

    # Step 5b: Wait and verify servers started successfully
    time.sleep(1.5)

    if config.dashboard_enabled:
        if _dash_error:
            print(f"  [DASHBOARD] FAILED: {_dash_error[0]}")
        elif dash_thread.is_alive():
            print(f"  [DASHBOARD] Running on http://localhost:{config.dashboard_port}")
        else:
            print(f"  [DASHBOARD] FAILED: thread exited unexpectedly")

    if config.api_enabled:
        if _api_error:
            print(f"  [CLOUD API] FAILED: {_api_error[0]}")
        elif api_thread.is_alive():
            print(f"  [CLOUD API] Running on http://localhost:{config.api_port}")
            print(f"  [CLOUD API] Docs at http://localhost:{config.api_port}/docs")
            auth_disabled = os.environ.get("SYNRIX_AUTH_DISABLED", "").strip() == "1"
            if auth_disabled:
                print(f"  [CLOUD API] Auth: DISABLED (development mode)")
            elif config.api_key:
                print(f"  [CLOUD API] Auth: API key required")
            else:
                print(f"  [CLOUD API] Auth: OPEN (set SYNRIX_API_KEY for production)")
        else:
            print(f"  [CLOUD API] FAILED: thread exited unexpectedly")

    # Step 6: Open browser (servers already waited on above)
    if not args.no_browser and config.dashboard_enabled and not _dash_error:
        webbrowser.open(f"http://localhost:{config.dashboard_port}")

    # Step 7: Optionally start demo
    if args.demo:
        time.sleep(2)

        print("\n  [DEMO] Starting Research Team demo (4 agents)...\n")
        from synrix_runtime.demo.three_agent_demo import run_demo

        def run_demo_thread():
            try:
                run_demo(keep_alive=True)
            except Exception as e:
                print(f"  [DEMO ERROR] {e}")
                import traceback
                traceback.print_exc()

        demo_thread = threading.Thread(target=run_demo_thread, daemon=True)
        demo_thread.start()

    # Keep running
    print(f"\n  Backend: {backend_type} | Data: {config.data_dir}")
    print("  Press Ctrl+C to stop.\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n  [OCTOPODA] Shutting down...")
        daemon.shutdown()
        print("  [OCTOPODA] Goodbye.\n")


if __name__ == "__main__":
    main()
