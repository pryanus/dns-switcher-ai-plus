"""
Build script to compile DNS Switcher into a single portable EXE using PyInstaller.
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).parent.resolve()
SRC_DIR = ROOT_DIR / "src"
DIST_DIR = ROOT_DIR / "dist"
BUILD_DIR = ROOT_DIR / "build"
ICON_PATH = SRC_DIR / "assets" / "icon.ico"
MAIN_SCRIPT = SRC_DIR / "main.py"


def build():
    print("=== Building DNS Switcher Portable EXE ===")
    
    # Clean previous build artifacts
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR, ignore_errors=True)
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR, ignore_errors=True)

    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--name", "DNS_Switcher",
        "--onefile",
        "--windowed",
        "--uac-admin",
        "--clean",
        "--noconfirm",
        f"--icon={ICON_PATH}",
        f"--add-data={SRC_DIR / 'assets'};assets",
        f"--paths={SRC_DIR}",
        str(MAIN_SCRIPT)
    ]

    print(f"Running: {' '.join(cmd)}")
    build_env = dict(os.environ)
    if os.name == "nt":
        # Не включать посторонние ICU/API DLL из PATH редактора в переносимый EXE.
        windows_dir = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        build_env["PATH"] = os.pathsep.join(map(str, [
            Path(sys.executable).parent, windows_dir / "System32", windows_dir,
        ]))
    res = subprocess.run(cmd, cwd=str(ROOT_DIR), env=build_env)
    if res.returncode != 0:
        print("Build failed with returncode:", res.returncode)
        sys.exit(res.returncode)

    exe_path = DIST_DIR / "DNS_Switcher.exe"
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"\n[SUCCESS] Portable EXE generated successfully!")
        print(f"Path: {exe_path}")
        print(f"Size: {size_mb:.1f} MB")
        
    else:
        print("[ERROR] DNS_Switcher.exe not found in dist/")
        sys.exit(1)


if __name__ == "__main__":
    build()
