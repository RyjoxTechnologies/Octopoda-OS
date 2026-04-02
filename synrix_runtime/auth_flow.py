"""
Octopoda Account Management
============================
Handles local config storage, signup flow, and API key validation.

Config is stored at ~/.octopoda/config.json
"""

import os
import json
import getpass
import sys
import logging

logger = logging.getLogger("octopoda.auth")

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".octopoda")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# Default cloud API URL
DEFAULT_API_URL = "https://api.octopodas.com"


def _load_config() -> dict:
    """Load config from ~/.octopoda/config.json"""
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_config(config: dict):
    """Save config to ~/.octopoda/config.json"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def get_api_key() -> str:
    """Get the stored API key, or empty string if none."""
    config = _load_config()
    return config.get("api_key", os.environ.get("OCTOPODA_API_KEY", ""))


def get_api_url() -> str:
    """Get the API URL."""
    config = _load_config()
    return config.get("api_url", os.environ.get("OCTOPODA_API_URL", DEFAULT_API_URL))


def save_api_key(key: str, api_url: str = None):
    """Save an API key to config."""
    config = _load_config()
    config["api_key"] = key
    if api_url:
        config["api_url"] = api_url
    _save_config(config)


def validate_key(api_key: str, api_url: str = None) -> bool:
    """Check if an API key is valid by hitting /v1/auth/me."""
    url = api_url or get_api_url()
    try:
        import requests
        resp = requests.get(
            f"{url}/v1/auth/me",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


def _interactive_signup(api_url: str = None) -> str:
    """Run the interactive signup flow in the terminal.

    Returns the API key on success, empty string on failure.
    """
    url = api_url or DEFAULT_API_URL

    print()
    print("=" * 60)
    print("  Welcome to Octopoda")
    print("  Persistent Memory for AI Agents")
    print("=" * 60)
    print()
    print("  An account is required to use Octopoda.")
    print("  It's free. Takes 30 seconds.")
    print()
    print("  [1] Sign up (new account)")
    print("  [2] Log in (existing account)")
    print("  [3] Enter API key manually")
    print()

    try:
        choice = input("  Choose [1/2/3]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n  Cancelled.")
        return ""

    if choice == "3":
        return _manual_key_entry()
    elif choice == "2":
        return _login_flow(url)
    else:
        return _signup_flow(url)


def _manual_key_entry() -> str:
    """Let user paste an existing API key."""
    print()
    try:
        key = input("  Paste your API key: ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""

    if not key.startswith("sk-octopoda-"):
        print("  Invalid key format. Keys start with sk-octopoda-")
        return ""

    print("  Validating...")
    if validate_key(key):
        save_api_key(key)
        print("  Key saved. You're good to go!")
        return key
    else:
        print("  Key is invalid or expired. Try signing up for a new one.")
        return ""


def _signup_flow(api_url: str) -> str:
    """Interactive signup with email verification."""
    import requests

    print()
    print("  --- Sign Up ---")
    print()

    try:
        email = input("  Email: ").strip()
        if not email or "@" not in email:
            print("  Invalid email.")
            return ""

        first_name = input("  First name: ").strip()
        if not first_name:
            print("  First name is required.")
            return ""

        last_name = input("  Last name: ").strip()
        if not last_name:
            print("  Last name is required.")
            return ""

        password = getpass.getpass("  Password (min 8 chars): ")
        if len(password) < 8:
            print("  Password must be at least 8 characters.")
            return ""
    except (EOFError, KeyboardInterrupt):
        print("\n  Cancelled.")
        return ""

    # Call signup endpoint
    print()
    print("  Creating account...")
    try:
        resp = requests.post(
            f"{api_url}/v1/auth/signup",
            json={
                "email": email,
                "password": password,
                "first_name": first_name,
                "last_name": last_name,
            },
            timeout=15,
        )
        data = resp.json()
    except Exception as e:
        print(f"  Connection error: {e}")
        print(f"  Make sure {api_url} is reachable.")
        return ""

    if resp.status_code == 409:
        print("  Account already exists for this email. Try logging in instead.")
        return _login_flow(api_url, prefill_email=email)

    if resp.status_code != 200:
        print(f"  Signup failed: {data.get('detail', 'Unknown error')}")
        return ""

    api_key = data.get("api_key", "")
    print(f"  Account created! Check your email for a verification code.")
    print()

    # Verification loop
    verified = _verify_flow(api_url, email)
    if not verified:
        print("  Verification failed. You can try again later with: octopoda login")
        return ""

    # Save and return
    if api_key:
        save_api_key(api_key, api_url)
        print()
        print("  You're all set! Your API key has been saved.")
        print(f"  Config: {CONFIG_FILE}")
        print()
    return api_key


def _login_flow(api_url: str, prefill_email: str = None) -> str:
    """Interactive login flow."""
    import requests

    print()
    print("  --- Log In ---")
    print()

    try:
        email = prefill_email or input("  Email: ").strip()
        if prefill_email:
            print(f"  Email: {email}")
        password = getpass.getpass("  Password: ")
    except (EOFError, KeyboardInterrupt):
        print("\n  Cancelled.")
        return ""

    print("  Logging in...")
    try:
        resp = requests.post(
            f"{api_url}/v1/auth/login",
            json={"email": email, "password": password},
            timeout=15,
        )
        data = resp.json()
    except Exception as e:
        print(f"  Connection error: {e}")
        return ""

    if resp.status_code != 200:
        print(f"  Login failed: {data.get('detail', 'Invalid email or password')}")
        return ""

    api_key = data.get("api_key", "")
    if api_key:
        save_api_key(api_key, api_url)
        print(f"  Logged in as {data.get('email', email)}!")
        print(f"  Plan: {data.get('plan', 'free')}")
        print(f"  Config saved: {CONFIG_FILE}")
        print()
    return api_key


def _verify_flow(api_url: str, email: str) -> bool:
    """Handle the email verification code entry."""
    import requests

    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            code = input(f"  Enter 6-digit code from your email: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled.")
            return False

        if not code or len(code) != 6 or not code.isdigit():
            print("  Code must be 6 digits.")
            continue

        try:
            resp = requests.post(
                f"{api_url}/v1/auth/verify",
                json={"email": email, "code": code},
                timeout=10,
            )
            if resp.status_code == 200:
                print("  Email verified!")
                return True
            else:
                remaining = max_attempts - attempt - 1
                if remaining > 0:
                    print(f"  Invalid code. {remaining} attempts remaining.")
                else:
                    print("  Too many failed attempts.")
        except Exception as e:
            print(f"  Error: {e}")

    return False


def ensure_authenticated(allow_local: bool = False) -> str:
    """Ensure the user has a valid API key. Returns the key.

    If no key is found and we're in an interactive terminal,
    runs the signup/login flow. If non-interactive (CI, scripts),
    raises an error with instructions.

    Args:
        allow_local: If True, skip auth for local-only usage (testing, CI).
                    Set via OCTOPODA_LOCAL_MODE=1 env var.
    """
    # Check environment override for local/testing mode
    if allow_local or os.environ.get("OCTOPODA_LOCAL_MODE", "").strip() in ("1", "true", "yes"):
        return ""

    # Check for existing key
    key = get_api_key()
    if key:
        return key

    # Check if we're in an interactive terminal
    if sys.stdin.isatty() and sys.stdout.isatty():
        key = _interactive_signup()
        if key:
            return key
        # User cancelled or failed — let them continue in local mode
        print()
        print("  No account configured. Running in limited local mode.")
        print("  To sign up later: python -c \"from synrix_runtime.auth_flow import _interactive_signup; _interactive_signup()\"")
        print()
        return ""
    else:
        # Non-interactive: log once, not per agent
        if not getattr(ensure_authenticated, "_warned", False):
            ensure_authenticated._warned = True
            logger.warning(
                "No Octopoda API key found. Set OCTOPODA_API_KEY environment variable "
                "or run interactively to sign up. Running in local mode. "
                "Sign up free at https://octopodas.com"
            )
        return ""


def _cli_login():
    """CLI entry point for octopoda-login command."""
    key = get_api_key()
    if key:
        print(f"  Already logged in. Key: {key[:20]}...")
        print(f"  Config: {CONFIG_FILE}")
        print()
        try:
            choice = input("  Log in with a different account? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if choice != "y":
            return

    result = _interactive_signup()
    if result:
        print("  Ready to use Octopoda!")
    else:
        print("  No account configured. Try again with: octopoda-login")


def _cli_status():
    """Show current auth status."""
    key = get_api_key()
    url = get_api_url()
    if key:
        print(f"  Logged in")
        print(f"  API key: {key[:20]}...")
        print(f"  API URL: {url}")
        print(f"  Config:  {CONFIG_FILE}")
        valid = validate_key(key, url)
        print(f"  Key valid: {'Yes' if valid else 'No (expired or revoked)'}")
    else:
        print("  Not logged in.")
        print("  Run: octopoda-login")
