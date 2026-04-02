"""
SYNRIX Engine Management

Handles engine detection, installation, and management.
"""
import logging

logger = logging.getLogger(__name__)


import os
import sys
import platform
import subprocess
import shutil
from pathlib import Path
from typing import Optional, Tuple
import requests
from .exceptions import SynrixError


# Engine download: set SYNRIX_ENGINE_DOWNLOAD_BASE_URL for auto-download (no default)
ENGINE_BASE_URL = os.getenv("SYNRIX_ENGINE_DOWNLOAD_BASE_URL", "").strip()
ENGINE_VERSION = "0.1.0"
GITHUB_RELEASES = "https://github.com/RYJOX-Technologies/Synrix-Memory-Engine/releases"


def get_platform_string() -> str:
    """Get platform string for engine binary."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    
    if system == "linux":
        if machine in ("x86_64", "amd64"):
            return "linux-x86_64"
        elif machine in ("aarch64", "arm64"):
            return "linux-arm64"
    elif system == "darwin":
        if machine in ("x86_64", "amd64"):
            return "darwin-x86_64"
        elif machine in ("arm64", "aarch64"):
            return "darwin-arm64"
    elif system == "windows":
        if machine in ("x86_64", "amd64"):
            return "windows-x86_64"
    
    raise SynrixError(f"Unsupported platform: {system} {machine}")


def get_engine_filename() -> str:
    """Get engine binary filename for current platform."""
    platform_str = get_platform_string()
    if platform_str.startswith("windows"):
        return f"synrix-server-evaluation-{ENGINE_VERSION}-{platform_str}.exe"
    else:
        return f"synrix-server-evaluation-{ENGINE_VERSION}-{platform_str}"


def get_engine_path() -> Path:
    """Get path where engine should be installed."""
    # Use user's home directory for engine storage
    home = Path.home()
    engine_dir = home / ".synrix" / "bin"
    engine_dir.mkdir(parents=True, exist_ok=True)
    return engine_dir / get_engine_filename()


def find_engine() -> Optional[Path]:
    """Find SYNRIX engine binary.
    
    Checks in order:
    1. User's ~/.synrix/bin directory
    2. Current directory
    3. PATH environment variable
    
    Returns:
        Path to engine binary if found, None otherwise
    """
    engine_name = get_engine_filename()
    
    # Check ~/.synrix/bin
    engine_path = get_engine_path()
    if engine_path.exists() and engine_path.is_file():
        if os.access(engine_path, os.X_OK):
            return engine_path
    
    # Check current directory
    current_dir = Path.cwd() / engine_name
    if current_dir.exists() and current_dir.is_file():
        if os.access(current_dir, os.X_OK):
            return current_dir
    
    # Check PATH
    engine_in_path = shutil.which(engine_name)
    if engine_in_path:
        return Path(engine_in_path)
    
    # Also check for synrix-server-evaluation without version
    engine_in_path = shutil.which("synrix-server-evaluation")
    if engine_in_path:
        return Path(engine_in_path)
    
    return None


def check_engine_running(port: int = 6334) -> bool:
    """Check if SYNRIX engine is already running on the given port."""
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("localhost", port))
        sock.close()
        return result == 0
    except Exception:
        return False


def download_engine(progress: bool = True) -> Path:
    """Download SYNRIX engine binary.
    
    Args:
        progress: Show download progress
        
    Returns:
        Path to downloaded engine binary
        
    Raises:
        SynrixError: If download fails
    """
    platform_str = get_platform_string()
    engine_filename = get_engine_filename()
    engine_path = get_engine_path()
    
    if not ENGINE_BASE_URL:
        raise SynrixError(
            "Engine auto-download is not configured. Set SYNRIX_ENGINE_DOWNLOAD_BASE_URL to a base URL, "
            f"or download the engine manually from {GITHUB_RELEASES}"
        )
    download_url = f"{ENGINE_BASE_URL.rstrip('/')}/{engine_filename}"
    
    logger.info(f"Downloading SYNRIX engine for {platform_str}...")
    logger.info(f"URL: {download_url}")
    
    try:
        response = requests.get(download_url, stream=True, timeout=30)
        response.raise_for_status()
        
        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0
        
        with open(engine_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress and total_size > 0:
                        percent = (downloaded / total_size) * 100
                        logger.info(f"\rProgress: {percent:.1f}% ({downloaded}/{total_size} bytes)", end="", flush=True)
        
        if progress:
            print()  # New line after progress
        
        # Make executable (Unix-like systems)
        if not platform_str.startswith("windows"):
            os.chmod(engine_path, 0o755)
        
        logger.info(f"✅ Engine downloaded to: {engine_path}")
        return engine_path
        
    except requests.exceptions.RequestException as e:
        raise SynrixError(f"Failed to download engine: {e}")
    except Exception as e:
        # Clean up partial download
        if engine_path.exists():
            engine_path.unlink()
        raise SynrixError(f"Failed to install engine: {e}")


def verify_engine(engine_path: Path) -> bool:
    """Verify that engine binary works."""
    try:
        result = subprocess.run(
            [str(engine_path), "--version"],
            capture_output=True,
            timeout=5,
            text=True
        )
        return result.returncode == 0
    except Exception:
        return False


def install_engine(force: bool = False) -> Path:
    """Install SYNRIX engine binary.
    
    Args:
        force: Force re-download even if engine exists
        
    Returns:
        Path to installed engine binary
        
    Raises:
        SynrixError: If installation fails
    """
    engine_path = get_engine_path()
    
    # Check if already installed
    if engine_path.exists() and not force:
        logger.info(f"Engine already installed at: {engine_path}")
        if verify_engine(engine_path):
            logger.info("✅ Engine verified and ready to use")
            return engine_path
        else:
            logger.error("⚠️  Existing engine failed verification, re-downloading...")
            engine_path.unlink()
    
    # Download engine
    try:
        engine_path = download_engine()
        
        # Verify
        if verify_engine(engine_path):
            logger.info("✅ Engine installed and verified")
            return engine_path
        else:
            raise SynrixError("Downloaded engine failed verification")
            
    except Exception as e:
        raise SynrixError(f"Failed to install engine: {e}")


def init() -> Tuple[bool, Optional[Path], Optional[str]]:
    """Initialize SYNRIX - check for engine and return status.
    
    Returns:
        Tuple of (engine_found, engine_path, error_message)
    """
    engine_path = find_engine()
    
    if engine_path:
        return True, engine_path, None
    else:
        error_msg = (
            "SYNRIX engine not found.\n"
            "Run: synrix install-engine"
        )
        return False, None, error_msg
