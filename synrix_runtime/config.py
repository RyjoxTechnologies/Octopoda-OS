"""
Synrix Runtime Configuration
==============================
Production configuration loaded from environment variables.
"""

import os
from dataclasses import dataclass


@dataclass
class SynrixConfig:
    """Production configuration for Synrix Agent Runtime."""

    # Backend: "auto", "sqlite", "lattice", "mock"
    backend: str = "sqlite"

    # Data directory
    data_dir: str = "~/.synrix/data"

    # SQLite settings
    sqlite_db_name: str = "synrix.db"

    # Lattice settings
    lattice_file: str = "synrix.lattice"
    lattice_max_nodes: int = 25000

    # Cloud API server
    api_host: str = "0.0.0.0"
    api_port: int = 8741
    api_enabled: bool = True

    # Dashboard
    dashboard_port: int = 7842
    dashboard_enabled: bool = True

    # Authentication (REST API)
    api_key: str = ""

    # Licensing (tier enforcement — separate from API auth)
    license_key: str = ""

    # Garbage collection
    gc_enabled: bool = True
    gc_interval_hours: int = 6
    gc_metrics_days: int = 7
    gc_events_days: int = 14
    gc_alerts_days: int = 14
    gc_audit_days: int = 90
    gc_max_snapshots: int = 10

    # Logging
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "SynrixConfig":
        """Load configuration from environment variables."""
        return cls(
            backend=os.getenv("SYNRIX_BACKEND", "sqlite"),
            # Audit fix §14 #8 / P1 #7 — accept OCTOPODA_DATA_DIR for per-project DBs.
            # SYNRIX_DATA_DIR is kept for backwards compat. OCTOPODA_DATA_DIR wins.
            data_dir=os.path.expanduser(
                os.getenv("OCTOPODA_DATA_DIR")
                or os.getenv("SYNRIX_DATA_DIR", "~/.synrix/data")
            ),
            sqlite_db_name=os.getenv("SYNRIX_SQLITE_DB", "synrix.db"),
            lattice_file=os.getenv("SYNRIX_LATTICE_FILE", "synrix.lattice"),
            lattice_max_nodes=int(os.getenv("SYNRIX_MAX_NODES", "25000")),
            api_host=os.getenv("SYNRIX_API_HOST", "0.0.0.0"),
            api_port=int(os.getenv("SYNRIX_API_PORT", "8741")),
            api_enabled=os.getenv("SYNRIX_API_ENABLED", "true").lower() == "true",
            dashboard_port=int(os.getenv("SYNRIX_DASHBOARD_PORT", "7842")),
            dashboard_enabled=os.getenv("SYNRIX_DASHBOARD", "true").lower() == "true",
            api_key=os.getenv("SYNRIX_API_KEY", ""),
            license_key=os.getenv("SYNRIX_LICENSE_KEY", ""),
            gc_enabled=os.getenv("SYNRIX_GC_ENABLED", "true").lower() == "true",
            gc_interval_hours=int(os.getenv("SYNRIX_GC_INTERVAL_HOURS", "6")),
            gc_metrics_days=int(os.getenv("SYNRIX_GC_METRICS_DAYS", "7")),
            gc_events_days=int(os.getenv("SYNRIX_GC_EVENTS_DAYS", "14")),
            gc_alerts_days=int(os.getenv("SYNRIX_GC_ALERTS_DAYS", "14")),
            gc_audit_days=int(os.getenv("SYNRIX_GC_AUDIT_DAYS", "90")),
            gc_max_snapshots=int(os.getenv("SYNRIX_GC_MAX_SNAPSHOTS", "10")),
            log_level=os.getenv("SYNRIX_LOG_LEVEL", "INFO"),
        )

    def resolve_backend(self) -> str:
        """Auto-detect best available backend."""
        if self.backend in ("postgres", "sqlite", "lattice", "mock"):
            return self.backend
        if self.backend != "auto":
            return self.backend
        try:
            from synrix.raw_backend import _find_synrix_lib
            lib_path = _find_synrix_lib()
            if lib_path:
                import ctypes, sys
                # Add DLL directory so dependency DLLs are found
                lib_dir = os.path.dirname(os.path.abspath(lib_path))
                if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
                    os.add_dll_directory(lib_dir)
                ctypes.CDLL(lib_path)
                return "lattice"
        except Exception:
            pass
        return "sqlite"

    def get_sqlite_path(self) -> str:
        os.makedirs(self.data_dir, exist_ok=True)
        return os.path.join(self.data_dir, self.sqlite_db_name)

    def get_lattice_path(self) -> str:
        os.makedirs(self.data_dir, exist_ok=True)
        return os.path.join(self.data_dir, self.lattice_file)

    def get_backend_kwargs(self) -> dict:
        """Get kwargs for get_synrix_backend() based on config."""
        backend_type = self.resolve_backend()
        if backend_type == "postgres":
            return {
                "backend": "postgres",
                "dsn": os.environ.get("DATABASE_URL", ""),
                "use_mock": False,
            }
        return {
            "backend": backend_type,
            "sqlite_path": self.get_sqlite_path(),
            "lattice_path": self.get_lattice_path(),
            "use_mock": False,
        }
