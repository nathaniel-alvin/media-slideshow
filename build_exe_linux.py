#!/usr/bin/env python3
"""Build MediaSlideshow.exe using a Docker Windows container."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST_EXE = ROOT / "dist" / "MediaSlideshow.exe"

def main() -> int:
    # Remove old executable if it exists
    if DIST_EXE.exists():
        DIST_EXE.unlink()

    # The Docker command that runs the Windows environment via Wine
    # It mounts your current folder, installs PyQt6 and PyInstaller for Windows,
    # and then runs your exact PyInstaller build command.
    docker_cmd = [
        "docker", "run", "--rm",
        "-v", f"{ROOT}:/workspace",
        "-w", "/workspace",
        "tobix/pywine:3.11",
        "sh", "-c",
        "wine python -m pip install PyQt6 pyinstaller && "
        "wine pyinstaller --noconfirm --onefile --windowed --noupx --name MediaSlideshow --collect-all PyQt6 slideshow.py"
    ]

    print("Spinning up Docker to build Windows executable (this will take a few minutes)...")
    
    try:
        # Run the Docker container
        subprocess.check_call(docker_cmd, cwd=ROOT)
    except subprocess.CalledProcessError:
        print("Build failed: Docker command encountered an error.", file=sys.stderr)
        return 1
    except FileNotFoundError:
        print("Build failed: Docker is not installed or not in PATH.", file=sys.stderr)
        return 1

    # Verify the build succeeded
    if not DIST_EXE.exists():
        print("Build failed: MediaSlideshow.exe was not created in the dist folder.", file=sys.stderr)
        return 1

    # Move to the release directory
    release_dir = ROOT / "release"
    release_dir.mkdir(exist_ok=True)
    release_exe = release_dir / "MediaSlideshow.exe"
    shutil.copy2(DIST_EXE, release_exe)

    print()
    print("Build complete.")
    print(f"  {release_exe}")
    print()
    print("Double-click MediaSlideshow.exe in the release folder to run the app on Windows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
