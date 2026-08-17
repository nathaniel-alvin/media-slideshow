#!/usr/bin/env python3
"""Build MediaSlideshow.exe with PyInstaller."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST_EXE = ROOT / "dist" / "MediaSlideshow.exe"


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    if DIST_EXE.exists():
        DIST_EXE.unlink()

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name",
        "MediaSlideshow",
        "--collect-all",
        "PyQt6",
        str(ROOT / "slideshow.py"),
    ]

    print("Building executable (this may take a few minutes)...")
    subprocess.check_call(cmd, cwd=ROOT)

    if not DIST_EXE.exists():
        print("Build failed: MediaSlideshow.exe was not created.", file=sys.stderr)
        return 1

    release_dir = ROOT / "release"
    release_dir.mkdir(exist_ok=True)
    release_exe = release_dir / "MediaSlideshow.exe"
    shutil.copy2(DIST_EXE, release_exe)

    print()
    print("Build complete.")
    print(f"  {release_exe}")
    print()
    print("Double-click MediaSlideshow.exe in the release folder to run the app.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
