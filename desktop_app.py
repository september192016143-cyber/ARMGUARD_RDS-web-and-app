"""
ARMGUARD RDS — Desktop Application Launcher

Starts Django inside an embedded Waitress WSGI server on a free loopback port,
then opens a native desktop window via pywebview (Edge WebView2 on Windows).

Requirements (in addition to requirements.txt):
    pip install pywebview waitress

Usage:
    python desktop_app.py
    — or double-click run_desktop.bat —

Packaging to a standalone .exe (optional):
    pip install pyinstaller
    pyinstaller desktop_app.spec
"""
from __future__ import annotations

import os
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

# ── Resolve project paths ──────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = ROOT_DIR / "project"
ENV_FILE = ROOT_DIR / ".env"


# ── Bootstrap .env if it doesn't exist ────────────────────────────────────────
def _ensure_env() -> None:
    """Create a minimal .env with a generated secret key when none exists.

    This lets the app start on a fresh installation without a manual setup step.
    The generated key is written once and reused on every subsequent launch.
    """
    if ENV_FILE.exists():
        return

    print("[ARMGUARD] No .env file found — generating one automatically.")
    # secrets.token_urlsafe produces a cryptographically random URL-safe string.
    secret_key = secrets.token_urlsafe(50)
    ENV_FILE.write_text(
        f"DJANGO_SECRET_KEY={secret_key}\n"
        f"DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost\n",
        encoding="utf-8",
    )
    print(f"[ARMGUARD] .env written to: {ENV_FILE}")


# ── Find a free TCP port on loopback ──────────────────────────────────────────
def _find_free_port(start: int = 8765) -> int:
    for port in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free loopback port found in range 8765–8865.")


# ── Wait until the server is accepting connections ────────────────────────────
def _wait_for_server(port: int, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


# ── Resolve window icon ───────────────────────────────────────────────────────
def _get_app_icon() -> str | None:
    """Return the path to a .ico file for the pywebview window/taskbar icon.

    Priority:
      1. Custom logo uploaded via Settings (SystemSettings.app_logo) — converted
         to .ico on the fly using Pillow and cached in the system temp directory.
      2. Bundled favicon.ico (project/armguard/static/images/favicon.ico).
      3. None — pywebview will use the Python default icon.

    Called after django.setup() so the DB is available.
    """
    _fallback = ROOT_DIR / "project" / "armguard" / "static" / "images" / "favicon.ico"

    try:
        from armguard.apps.users.models import SystemSettings
        s = SystemSettings.get()
        if s.app_logo and s.app_logo.name:
            logo_path = Path(s.app_logo.path)
            if logo_path.exists():
                if logo_path.suffix.lower() == ".ico":
                    return str(logo_path)
                # Convert PNG/JPEG → .ico using Pillow (already a dependency).
                import tempfile
                from PIL import Image
                ico_path = Path(tempfile.gettempdir()) / "armguard_window_icon.ico"
                with Image.open(logo_path) as img:
                    img = img.convert("RGBA")
                    img.save(
                        str(ico_path),
                        format="ICO",
                        sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)],
                    )
                print(f"[ARMGUARD] Window icon: custom logo ({logo_path.name})")
                return str(ico_path)
    except Exception as exc:
        print(f"[ARMGUARD] Could not load custom logo for icon: {exc}")

    if _fallback.exists():
        return str(_fallback)
    return None


# ── Waitress server thread target ─────────────────────────────────────────────
def _run_server(port: int) -> None:
    from waitress import serve  # type: ignore[import-untyped]
    from armguard.wsgi import application  # Django must be set up before this

    print(f"[ARMGUARD] Server listening on http://127.0.0.1:{port}/")
    serve(
        application,
        host="127.0.0.1",
        port=port,
        threads=4,
        clear_untrusted_proxy_headers=True,
        # Waitress channel_timeout: drop idle keep-alive connections after 30 s
        # so file handles don't accumulate while the window is idle.
        channel_timeout=30,
    )


# ── Django initialisation ─────────────────────────────────────────────────────
def _setup_django(port: int) -> None:
    """Add project/ to sys.path, configure settings, and call django.setup()."""
    sys.path.insert(0, str(PROJECT_DIR))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "armguard.settings.desktop")
    # Tell Django to trust the Origin header sent by Edge WebView2 for CSRF.
    os.environ["CSRF_TRUSTED_ORIGINS"] = (
        f"http://127.0.0.1:{port},http://localhost:{port}"
    )
    import django
    django.setup()

    # Clear the rate-limit cache so counts from previous runs don't carry over.
    # This prevents the "submitting too quickly" false-positive on the login page
    # when the desktop app is restarted multiple times in a short window.
    try:
        from django.core.cache import cache
        cache.clear()
    except Exception:
        pass


# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    _ensure_env()

    port = _find_free_port()
    url = f"http://127.0.0.1:{port}/"

    _setup_django(port)

    # Start the server in a daemon thread — it will be killed automatically
    # when the pywebview window closes and the main thread exits.
    server_thread = threading.Thread(
        target=_run_server, args=(port,), daemon=True, name="armguard-server"
    )
    server_thread.start()

    print("[ARMGUARD] Waiting for server to be ready…")
    if not _wait_for_server(port):
        print(
            "[ARMGUARD] ERROR: Server did not become ready within 20 seconds.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[ARMGUARD] Ready — opening window at {url}")

    # Resolve icon after Django is set up so SystemSettings is queryable.
    _icon = _get_app_icon()

    # ── Start background sync thread (if configured) ──────────────────────────
    sync_url   = os.environ.get('SYNC_SERVER_URL', '').strip()
    sync_token = os.environ.get('SYNC_API_TOKEN',  '').strip()
    sync_enabled = os.environ.get('SYNC_ENABLED', 'True').strip().lower() not in ('false', '0', 'no')
    if sync_enabled and sync_url and sync_token:
        from armguard.sync_client import start_sync_thread
        interval = int(os.environ.get('SYNC_INTERVAL_MINUTES', '5'))
        start_sync_thread(sync_url, sync_token, interval)
        print(f"[ARMGUARD] Sync enabled → {sync_url} (every {interval} min)")
    elif sync_enabled and not (sync_url and sync_token):
        print("[ARMGUARD] Sync skipped — SYNC_SERVER_URL and SYNC_API_TOKEN not set in .env")

    import webview  # type: ignore[import-untyped]

    webview.create_window(
        "ARMGUARD RDS — Records & Dispensing System",
        url=url,
        width=1440,
        height=900,
        min_size=(1024, 600),
        resizable=True,
        # Prompt the user before closing to prevent accidental data loss mid-form.
        confirm_close=True,
        **(({'icon': _icon}) if _icon else {}),
    )
    # gui=None lets pywebview pick the best available renderer.
    # On Windows 10/11 this is Edge WebView2 (pre-installed).
    webview.start(debug=False)


if __name__ == "__main__":
    main()
