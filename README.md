# SceneTrim

[![Platform](https://img.shields.io/badge/Platform-Windows-blue.svg)](https://microsoft.com/windows)
[![Python](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](https://www.python.org/)
[![GUI](https://img.shields.io/badge/GUI-FreeSimpleGUI-orange.svg)](https://github.com/spyoungtech/FreeSimpleGUI)
[![FFmpeg](https://img.shields.io/badge/Engine-FFmpeg-red.svg)](https://ffmpeg.org/)
[![Author](https://img.shields.io/badge/Author-Baraa%20Hawamdeh-informational.svg)](https://github.com/baraa-hawamdeh)

A modern, high-performance desktop application for Windows designed to automatically cut, trim, and remove unwanted scenes or intervals from batches of video files using **FFmpeg**.

Built with a sleek dark-themed GUI in **FreeSimpleGUI**, SceneTrim supports hardware-accelerated GPU encoding via NVIDIA **NVENC** (`h264_nvenc`) with seamless automatic fallback to CPU (`libx264`).

---

## Table of Contents

- [Features](#features)
- [Quick Start (Portable EXE)](#quick-start-portable-exe)
- [Running from Source (Python)](#running-from-source-python)
- [Installing FFmpeg](#installing-ffmpeg)
- [Usage Guide](#usage-guide)
  - [Input & Output Folders](#input--output-folders)
  - [Syntax & Timestamp Rules](#syntax--timestamp-rules)
  - [Example Plan](#example-plan)
- [How It Works](#how-it-works)
- [Building the Standalone EXE](#building-the-standalone-exe)
- [Packaging for Distribution](#packaging-for-distribution)
- [Project Structure](#project-structure)
- [Troubleshooting & FAQ](#troubleshooting--faq)
- [Author](#author)

---

## Features

- **⚡ Hardware-Accelerated Encoding**: Automatically uses NVIDIA NVENC (`h264_nvenc`) for blazing fast encoding, falling back to multi-threaded CPU (`libx264`) if no compatible GPU is detected.
- **✂️ Batch Scene Removal**: Define exact timestamps to remove per video in a simple, human-readable text box.
- **🎨 Sleek Modern GUI**: Polished GitHub-dark inspired interface (`Segoe UI` + `Consolas`) with card-based sections, status badges, and live terminal logs.
- **📦 Completely Portable**: Runs as a standalone `.exe` without requiring Python, with automatic binary discovery for `ffmpeg.exe` and `ffprobe.exe`.
- **🛑 Subprocess & Cancel Control**: Gracefully stop running jobs at any moment without leaving zombie FFmpeg processes or corrupted files.
- **🔄 Multi-Format Compatibility**: Recursively discovers `.mp4`, `.mkv`, `.mov`, `.ts`, and `.m4v` files matching your episode names.

---

## Quick Start (Portable EXE)

If you downloaded the pre-built release package (`SceneTrim_release.zip`), **no Python installation is required**:

1. Extract `SceneTrim_release.zip`.
2. Ensure the folder contains:
   - `SceneTrim.exe`
   - `ffmpeg.exe`
   - `ffprobe.exe`
3. Double-click `SceneTrim.exe` to launch the application.

---

## Running from Source (Python)

### Prerequisites

- **Windows 10 / 11**
- **Python 3.10+**
- **FFmpeg & FFprobe** installed and available on system `PATH` (or placed in the project folder).

### Step-by-Step Setup

1. **Clone or navigate to the repository:**

   ```powershell
   git clone https://github.com/baraa-hawamdeh/SceneTrim.git
   cd SceneTrim
   ```

2. **Create and activate a virtual environment:**

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. **Install dependencies:**

   ```powershell
   pip install FreeSimpleGUI
   ```

4. **Launch the application:**

   ```powershell
   python SceneTrim.py
   ```

---

## Installing FFmpeg

If FFmpeg is not already installed on your system, install it using **WinGet**:

```powershell
winget install Gyan.FFmpeg
```

Restart your terminal or PowerShell and verify the installation:

```powershell
ffmpeg -version
ffprobe -version
```

### Manual Binary Location (Optional)

If FFmpeg is installed in a non-standard location and not in your `PATH`, you can set session environment variables:

```powershell
$env:FFMPEG  = "C:\path\to\ffmpeg\bin\ffmpeg.exe"
$env:FFPROBE = "C:\path\to\ffmpeg\bin\ffprobe.exe"
```

Or simply copy `ffmpeg.exe` and `ffprobe.exe` into the same directory as `SceneTrim.py` / `SceneTrim.exe`.

---

## Usage Guide

### Input & Output Folders

- **Input Folder**: Select the folder containing your source video files (SceneTrim searches subdirectories recursively).
- **Output Folder**: Select the destination folder where trimmed videos will be saved.

### Syntax & Timestamp Rules

Paste your episode cutting plan into the main text box according to these rules:

1. **First line of each block**: The video file name **without extension** (e.g., `E01` matches `E01.mp4`, `E01.mkv`, etc.).
2. **Subsequent lines**: The interval(s) to be **deleted/removed**.
3. **Supported Time Formats**:
   - Seconds: `90-120`
   - Minutes & Seconds: `01:30-02:00`
   - Hours, Minutes & Seconds: `01:15:30-01:20:00`
4. **No cuts (Passthrough)**: Write `clear` under an episode name to copy the video untouched.
5. **Separation**: Separate different episode blocks with an **empty line**.

### Example Plan

```text
E01
29:32-30:17
44:22-45:15

E02
clear

E03
01:15-02:00
17:33-17:42
```

In this example:
- `E01`: Sections `29:32` to `30:17` and `44:22` to `45:15` are deleted; remaining parts are stitched together seamlessly.
- `E02`: Copied as-is without any modifications.
- `E03`: Sections `01:15` to `02:00` and `17:33` to `17:42` are removed.

Click **Run Cutter** to start processing. The live progress, FFmpeg commands, and frame rates will stream into the **Live Process Log**.

---

## How It Works

1. **Duration Inspection**: Inspects the video stream duration via `ffprobe`.
2. **Inverted Interval Calculation**: Computes the complementary "keep" segments by subtracting unwanted cut ranges from total video length.
3. **Optimized Concat Pipeline**:
   - First attempts a single-pass `filter_complex` with NVIDIA NVENC hardware acceleration (`-c:v h264_nvenc -rc vbr -tune hq -cq 19 -b:v 0`).
   - If GPU encoding is unavailable or fails, automatically falls back to CPU encoding via `libx264` (`-crf 18 -preset slow`).
   - If streamcopy segments are viable, attempts direct bitstream demuxer concatenation.

---

## Building the Standalone EXE

You can compile SceneTrim into a standalone Windows `.exe` using **PyInstaller**:

```powershell
pip install pyinstaller
pyinstaller --noconsole --onefile --name SceneTrim SceneTrim.py
```

The resulting executable will be generated at:
```text
dist\SceneTrim.exe
```

---

## Packaging for Distribution

To prepare a portable release bundle that works on any Windows PC without prerequisites:

```powershell
# 1. Create release directory
New-Item -ItemType Directory -Path "SceneTrim_release" -Force

# 2. Copy the executable
Copy-Item "dist\SceneTrim.exe" -Destination "SceneTrim_release\" -Force

# 3. Copy FFmpeg binaries alongside the EXE
Copy-Item "C:\path\to\ffmpeg.exe" -Destination "SceneTrim_release\" -Force
Copy-Item "C:\path\to\ffprobe.exe" -Destination "SceneTrim_release\" -Force

# 4. Create zip archive
Compress-Archive -Path "SceneTrim_release" -DestinationPath "SceneTrim_release.zip" -Force
```

---

## Project Structure

```text
PySimpleGUI-Project/
├── .venv/                      # Python virtual environment (ignored)
├── build/                      # PyInstaller build files (ignored)
├── dist/                       # Compiled binaries (ignored)
│   ├── SceneTrim.exe
│   ├── ffmpeg.exe
│   └── ffprobe.exe
├── SceneTrim_release/          # Distribution folder (ignored)
├── SceneTrim_release.zip       # Portable zip bundle (ignored)
├── .gitignore                  # Git ignore rules
├── README.md                   # Project documentation
└── SceneTrim.py                # Main application script & GUI
```

---

## Troubleshooting & FAQ

### "FFmpeg Not Found" or `[WinError 2] The system cannot find the file specified`
SceneTrim searches for `ffmpeg.exe` and `ffprobe.exe` in:
1. Environment variables `$env:FFMPEG` and `$env:FFPROBE`.
2. Next to `SceneTrim.exe` / `SceneTrim.py` in the same directory.
3. Your current working directory.
4. System `PATH`.

Place `ffmpeg.exe` and `ffprobe.exe` directly in the same folder as `SceneTrim.exe` to resolve this immediately.

### The output video was not shortened
Make sure the cut intervals entered are within the actual duration of the video. If timestamps exceed the video length, SceneTrim ignores them and outputs the original file to prevent data loss.

### Processing is slower on some computers
If an NVIDIA GPU with NVENC is present, SceneTrim processes at high frame rates (100+ fps). If running on an Intel/AMD CPU without an NVIDIA card, SceneTrim falls back to `libx264` (CPU encoding), which is safe and produces identical quality but takes longer.

---

Author: Baraa Hawamdeh
