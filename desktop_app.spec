# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for ARMGUARD RDS Desktop Application.

Build command (run from the repo root with venv activated):
    pyinstaller desktop_app.spec

Output: dist\ARMGUARD_RDS\
  ARMGUARD_RDS.exe   ← launcher
  _internal\         ← bundled Python + Django code (managed by PyInstaller)
  data\              ← created on first launch (db.sqlite3, media/, logs/)

The installer\armguard_setup.iss Inno Setup script then wraps this folder
into a single Setup.exe that end-users can run.
"""
from PyInstaller.utils.hooks import collect_all, collect_data_files
import os

block_cipher = None

# ── Collect packages that use dynamic imports / data files ────────────────────
django_datas,           django_bins,           django_hidden           = collect_all('django')
drf_datas,              drf_bins,              drf_hidden              = collect_all('rest_framework')
drf_spec_datas,         drf_spec_bins,         drf_spec_hidden         = collect_all('drf_spectacular')
webview_datas,          webview_bins,          webview_hidden          = collect_all('webview')
whitenoise_datas,       whitenoise_bins,       whitenoise_hidden       = collect_all('whitenoise')
dotenv_datas,           dotenv_bins,           dotenv_hidden           = collect_all('dotenv')
PIL_datas,              PIL_bins,              PIL_hidden              = collect_all('PIL')
qrcode_datas,           qrcode_bins,           qrcode_hidden           = collect_all('qrcode')
fitz_datas,             fitz_bins,             fitz_hidden             = collect_all('fitz')  # PyMuPDF
django_otp_datas,       django_otp_bins,       django_otp_hidden       = collect_all('django_otp')
gspread_datas,          gspread_bins,          gspread_hidden          = collect_all('gspread')
google_datas,           google_bins,           google_hidden           = collect_all('google')

# ── App-specific data files ────────────────────────────────────────────────────
app_datas = [
    # Django apps, templates, static files, settings
    ('project/armguard',        'project/armguard'),
    ('project/utils',           'project/utils'),
    ('project/card_templates',  'project/card_templates'),
    ('project/manage.py',       'project'),
    # Fonts
    ('fonts',                   'fonts'),
]

all_datas = (
    app_datas
    + django_datas
    + drf_datas
    + drf_spec_datas
    + webview_datas
    + whitenoise_datas
    + dotenv_datas
    + PIL_datas
    + qrcode_datas
    + fitz_datas
    + django_otp_datas
    + gspread_datas
    + google_datas
)

all_binaries = (
    django_bins + drf_bins + drf_spec_bins + webview_bins + whitenoise_bins
    + dotenv_bins + PIL_bins + qrcode_bins + fitz_bins
    + django_otp_bins + gspread_bins + google_bins
)

hidden_imports = (
    django_hidden + drf_hidden + drf_spec_hidden + webview_hidden + whitenoise_hidden
    + dotenv_hidden + PIL_hidden + qrcode_hidden + fitz_hidden
    + django_otp_hidden + gspread_hidden + google_hidden + [
        # Django internals often missed by the analyser
        'django.template.defaulttags',
        'django.template.defaultfilters',
        'django.template.loader_tags',
        'django.contrib.admin.templatetags',
        'django.contrib.humanize',
        'django.contrib.humanize.templatetags',
        'django.contrib.humanize.templatetags.humanize',
        # DRF
        'rest_framework.authtoken',
        'rest_framework.authtoken.admin',
        # Our apps (explicit so auto-discovery works inside the bundle)
        'armguard',
        'armguard.wsgi',
        'armguard.settings',
        'armguard.settings.desktop',
        'armguard.apps.users',
        'armguard.apps.inventory',
        'armguard.apps.personnel',
        'armguard.apps.transactions',
        'armguard.apps.api',
        'armguard.apps.camera',
        'armguard.middleware',
        'armguard.utils',
        # WSGI server
        'waitress',
        'waitress.task',
        'waitress.server',
        'waitress.channel',
        'waitress.receiver',
        'waitress.runner',
        # HTTP client for sync
        'requests',
        'requests.adapters',
        'urllib3',
        # Excel import
        'openpyxl',
        # dotenv
        'dotenv',
    ]
)

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    ['desktop_app.py'],
    pathex=['.', 'project'],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy', 'pandas'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ARMGUARD_RDS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,           # No black console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='project/armguard/static/images/favicon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ARMGUARD_RDS',
)
