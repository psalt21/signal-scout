"""py2app build script for Signal Scout.

Build a standalone macOS .app:
    python setup.py py2app
"""

from setuptools import setup

APP = ["app.py"]
DATA_FILES = []

OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "LSUIElement": True,           # Menu bar only – no Dock icon
        "CFBundleName": "Signal Scout",
        "CFBundleDisplayName": "Signal Scout",
        "CFBundleIdentifier": "com.signalscout.app",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
    },
    "packages": [
        "rumps",
        "feedparser",
        "requests",
        "certifi",       # needed for HTTPS certificate validation
        "sgmllib",       # feedparser dependency
    ],
    "includes": [
        "config",
        "database",
        "collector",
        "summarizer",
        "ranking",
        "digest_server",
    ],
}

setup(
    name="Signal Scout",
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
