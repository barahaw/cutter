"""
build_exe.py - Build script to package AI-Powered Video Fixer for Windows using PyInstaller.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def build():
    root_dir = Path(__file__).resolve().parent
    dist_dir = root_dir / "dist"
    build_dir = root_dir / "build"

    print("=" * 60)
    print("Packaging AI-Powered Video Fixer for Windows")
    print("=" * 60)

    # PyInstaller command
    build_output = dist_dir / "build_output"
    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--noconfirm",
        "--name", "VideoFixer",
        "--onedir",
        "--windowed",
        "--distpath", str(build_output),
        "--add-data", f"{root_dir / 'src'}{os.pathsep}src",
        "--hidden-import", "FreeSimpleGUI",
        "--hidden-import", "google.genai",
        "--hidden-import", "pydantic",
        "--hidden-import", "dotenv",
        str(root_dir / "app.py"),
    ]

    print(f"Running command: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=root_dir)

    if res.returncode != 0:
        print("\n[ERROR] PyInstaller build failed!")
        sys.exit(res.returncode)

    # Post-build packaging
    target_dist = dist_dir / "VideoFixer"
    target_dist.mkdir(parents=True, exist_ok=True)
    built_source = build_output / "VideoFixer"

    # Copy built files
    for item in built_source.iterdir():
        dest_item = target_dist / item.name
        if item.is_dir():
            shutil.copytree(item, dest_item, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest_item)

    print(f"\n[SUCCESS] Build completed at: {target_dist}")

    # Copy .env and .env.example next to the executable
    example_env = root_dir / ".env.example"
    if example_env.is_file():
        shutil.copy2(example_env, target_dist / ".env.example")
        print("Copied .env.example to release directory.")

    real_env = root_dir / ".env"
    if real_env.is_file():
        shutil.copy2(real_env, target_dist / ".env")
        print("Copied configured .env to release directory.")

    # Locate ffmpeg/ffprobe and copy next to the exe if available
    ffmpeg_bin = shutil.which("ffmpeg")
    ffprobe_bin = shutil.which("ffprobe")

    bin_dest = target_dist
    if ffmpeg_bin and os.path.isfile(ffmpeg_bin):
        shutil.copy2(ffmpeg_bin, bin_dest / "ffmpeg.exe")
        print("Bundled ffmpeg.exe next to executable.")
    if ffprobe_bin and os.path.isfile(ffprobe_bin):
        shutil.copy2(ffprobe_bin, bin_dest / "ffprobe.exe")
        print("Bundled ffprobe.exe next to executable.")

    print("\nRelease folder ready at:", target_dist)
    print("To configure Gemini AI, copy .env.example to .env in that folder and add your GEMINI_API_KEY.")


if __name__ == "__main__":
    build()
