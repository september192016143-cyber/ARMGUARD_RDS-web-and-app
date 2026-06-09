"""
ARMGUARD — Desktop (local) settings.

Runs the application on localhost via an embedded Waitress WSGI server
inside a native pywebview window.  No Nginx, no SSL, no collectstatic needed.

DJANGO_SETTINGS_MODULE is set automatically by desktop_app.py.
"""
import os
from .base import *  # noqa: F401, F403

# DEBUG=True so WhiteNoise serves static files directly from STATICFILES_DIRS
# without requiring a prior `collectstatic` run.  Acceptable risk: the server
# is bound to 127.0.0.1 and is only reachable from the local machine.
DEBUG = True

# Loopback only — the embedded Waitress server is not reachable from the network.
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']

# CSRF: set by desktop_app.py before django.setup() via the environment variable
# CSRF_TRUSTED_ORIGINS=http://127.0.0.1:<port>.  Needed so Django accepts the
# Origin header that Edge WebView2 attaches to POST requests.
_origins = os.environ.get('CSRF_TRUSTED_ORIGINS', '')
CSRF_TRUSTED_ORIGINS = [o.strip() for o in _origins.split(',') if o.strip()]

# No HTTPS in desktop mode.
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Use plain filesystem storage — consistent with DEBUG=True, no manifest needed.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Enable the REST API in desktop mode (same as development).
ARMGUARD_API_ENABLED = os.environ.get('ARMGUARD_API_ENABLED', 'True') == 'True'

# SSL cert path is server-only.  Empty string → os.path.isfile('') == False
# so the ssl-cert-status endpoint returns {"cert_mtime": 0.0} without error.
SSL_CERT_PATH = ''

# Sync settings — read by desktop_app.py before Django is fully started.
# They are documented here for reference; the actual reads happen in
# desktop_app.py via os.environ after load_dotenv() runs in base.py.
SYNC_SERVER_URL       = os.environ.get('SYNC_SERVER_URL', '')
SYNC_API_TOKEN        = os.environ.get('SYNC_API_TOKEN', '')
SYNC_INTERVAL_MINUTES = int(os.environ.get('SYNC_INTERVAL_MINUTES', '5'))
SYNC_ENABLED          = os.environ.get('SYNC_ENABLED', 'True').strip().lower() not in ('false', '0', 'no')

# ── PyInstaller bundle: redirect writable data outside _internal/ ─────────────
# When the app is packaged as a .exe, desktop_app.py sets ARMGUARD_DATA_DIR to
# <install_dir>/data/ so that database, media, and logs survive app upgrades.
# In development mode this variable is not set and BASE_DIR paths are used as-is.
import sys as _sys
_data_dir_env = os.environ.get('ARMGUARD_DATA_DIR', '')
if _data_dir_env:
    from pathlib import Path as _Path
    _DATA = _Path(_data_dir_env)
    _DATA.mkdir(parents=True, exist_ok=True)
    (_DATA / 'media').mkdir(exist_ok=True)
    (_DATA / 'logs').mkdir(exist_ok=True)
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': _DATA / 'db.sqlite3',
            'OPTIONS': {'timeout': 30},
        }
    }
    MEDIA_ROOT = _DATA / 'media'
    LOG_DIR    = _DATA / 'logs'

