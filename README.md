# SceneTrim

[![Platform](https://img.shields.io/badge/Platform-Windows-blue.svg)](https://microsoft.com/windows)
[![Python](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](https://www.python.org/)
[![GUI](https://img.shields.io/badge/GUI-FreeSimpleGUI-orange.svg)](https://github.com/spyoungtech/FreeSimpleGUI)
[![FFmpeg](https://img.shields.io/badge/Engine-FFmpeg-red.svg)](https://ffmpeg.org/)
[![Author](https://img.shields.io/badge/Author-Baraa%20Hawamdeh-informational.svg)](https://github.com/baraa-hawamdeh)

A modern, high-performance desktop application for Windows designed to automatically cut, trim, and remove unwanted scenes or intervals from batches of video files using **FFmpeg**. It also includes a **Fixer** tool that repairs MP4 files that keep "loading" on phones, without re-encoding.

Built with a sleek dark-themed GUI in **FreeSimpleGUI**, SceneTrim supports hardware-accelerated GPU encoding via NVIDIA **NVENC** (`h264_nvenc`) with seamless automatic fallback to CPU (`libx264`).

---

## Table of Contents

- [Features](#features)
- [Quick Start (Portable EXE)](#quick-start-portable-exe)
- [Running from Source (Python)](#running-from-source-python)
- [Installing FFmpeg](#installing-ffmpeg)
- [Usage Guide](#usage-guide)
  - [Cutter Tab](#cutter-tab)
  - [Fixer Tab](#fixer-tab)
  - [Fixer from the Command Line](#fixer-from-the-command-line)
- [How It Works](#how-it-works)
- [Building the Standalone EXE](#building-the-standalone-exe)
- [Packaging for Distribution](#packaging-for-distribution)
- [Project Structure](#project-structure)
- [Troubleshooting & FAQ](#troubleshooting--faq)
- [Author](#author)

---

## Features

### Cutter

- **⚡ Hardware-Accelerated Encoding**: Automatically uses NVIDIA NVENC (`h264_nvenc`) for fast encoding, falling back to CPU (`libx264`) if the GPU encoder is unavailable or fails.
- **✂️ Batch Scene Removal**: Define exact timestamps to remove per video in a simple, human-readable text box.
- **🚀 Instant Phone Playback**: Final output files are written with `-movflags +faststart`, so the index is at the start of the file and players begin playback immediately.
- **🛑 Subprocess & Cancel Control**: Stop running jobs at any moment; the running FFmpeg process is killed.
- **🔄 Multi-Format Input**: Recursively discovers `.mp4`, `.mkv`, `.mov`, `.ts`, `.m4v`, `.avi`, and `.webm` files matching your episode names.

### Fixer

- **🔍 Detects slow-start MP4s**: Reads the top-level MP4 atoms and checks whether the `moov` atom (the file index) is stored after `mdat`. Files like this keep "loading" on phones because the player has to reach the end of the file first.
- **🛠️ Lossless fix**: Remuxes with `-movflags +faststart` and stream copy. There is **no re-encoding**, so there is no quality loss and large files are processed quickly.
- **🧹 Video + audio only**: Closed-caption and other subtitle streams are dropped from the output.
- **📋 Status table**: Each file is shown as `ok`, `needs-fix`, `needs-reencode`, `unknown`, `fixing...`, `done`, `failed`, or `cancelled`.
- **📦 Batch processing** with a progress bar for the current file, an overall counter, and a **Stop** button.
- **🔒 Safe by design**: The source file is never overwritten. Output is written to a temporary `.part.mp4` file, verified (`moov` first, duration matches the source), and only then renamed.
- **⚙️ Options**: Optional output folder (empty = next to the source) and a filename suffix (default `_fixed`).

### General

- **🎨 Sleek Modern GUI**: Dark interface (`Segoe UI` + `Consolas`) with two tabs (Cutter, Fixer) and a shared live process log.
- **📦 Portable**: Runs as a standalone `.exe` without Python, with automatic discovery of `ffmpeg.exe` and `ffprobe.exe`.

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
- **FFmpeg & FFprobe** available on the system `PATH` (or placed next to the script).

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

`fixer.py` must stay in the same folder as `SceneTrim.py`, because the Fixer tab imports it.

---

## Installing FFmpeg

If FFmpeg is not already installed on your system, install it using **WinGet**:

```powershell
winget install Gyan.FFmpeg
```

Restart your terminal and verify the installation:

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

### Cutter Tab

**Input & Output Folders**

- **Input Folder**: the folder containing your source videos (subfolders are searched recursively).
- **Output Folder**: the destination for trimmed videos. It must be different from the input folder, so originals can never be overwritten.

**Syntax & Timestamp Rules**

1. **First line of each block**: the video file name **without extension** (e.g., `E01` matches `E01.mp4`, `E01.mkv`, etc.).
2. **Following lines**: the interval(s) to be **deleted**.
3. **Supported time formats**:
   - Seconds: `90-120`
   - Minutes & seconds: `01:30-02:00`
   - Hours, minutes & seconds: `01:15:30-01:20:00`
4. **No cuts (passthrough)**: write `clear` under a name to copy the video without cutting.
5. **Separation**: separate blocks with an **empty line**.

**Example Plan**

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

- `E01`: `29:32`-`30:17` and `44:22`-`45:15` are removed; the remaining parts are stitched together.
- `E02`: copied without cutting.
- `E03`: `01:15`-`02:00` and `17:33`-`17:42` are removed.

Click **Run Cutter**. Progress and FFmpeg output stream into the **Live Process Log**.

### Fixer Tab

1. Add videos with **Add Files** or **Add Folder** (use **Remove Selected** or **Clear** to edit the list).
2. Click **Check All**. Each file gets a status:
   - `ok`: index is at the start and the video is H.264 / `yuv420p`. Nothing to fix.
   - `needs-fix`: the `moov` atom is at the end. This is what the Fixer repairs.
   - `needs-reencode`: the file is not H.264 / `yuv420p`, so a remux alone will not make it phone-friendly.
   - `unknown`: the MP4 structure could not be determined.
3. (Optional) Set an **Output Folder** and a **Suffix**. With an empty output folder, results are saved next to the source as `<name>_fixed.mp4`.
4. Click **Fix Needed**. Only `needs-fix` files are processed. Use **Stop** to cancel at any time; the temporary `.part.mp4` file is deleted.

Safety rules: the source is never overwritten, an existing output file is skipped with a warning, and an empty suffix combined with the source folder as the output is blocked.

The Cutter and the Fixer cannot run at the same time.

### Fixer from the Command Line

`fixer.py` also works as a standalone script:

```powershell
# Check only (nothing is modified)
python fixer.py video.mp4 --check-only

# Fix a file (writes video_fixed.mp4 next to it)
python fixer.py video.mp4

# Fix a whole folder into another folder with a custom suffix
python fixer.py "C:\Videos" --outdir "C:\Videos\fixed" --suffix _fixed
```

Options: `--outdir`, `--suffix` (default `_fixed`), `--check-only`. When a folder is given, `.mp4`, `.m4v`, and `.mov` files in it are processed. In CLI mode, `fixer.py` looks for `ffmpeg.exe` / `ffprobe.exe` next to the script and then in `PATH`.

---

## How It Works

### Cutter

1. **Duration inspection** via `ffprobe`.
2. **Inverted interval calculation**: the "keep" segments are computed by subtracting the unwanted ranges from the total duration.
3. **Strategies, tried in order** until one succeeds:
   1. A single `filter_complex` trim/concat pass with NVENC (`-c:v h264_nvenc -rc vbr -tune hq -cq 19 -b:v 0`), then CPU `libx264` (`-crf 18 -preset slow`).
   2. Cutting each keep segment into a temporary part (stream copy, then NVENC, then CPU) and joining them with the concat demuxer.
   3. Re-encoding the parts on CPU and joining them.
   4. As a last resort, copying the original file.
4. Final output files are written with `-movflags +faststart`.

### Fixer

1. `fixer.py` walks the top-level MP4 atoms (headers only, so it is instant even on multi-GB files) and compares the offsets of `moov` and `mdat`.
2. `ffprobe` reads the codec, profile, pixel format, and duration.
3. For `needs-fix` files, FFmpeg runs `-map 0:v -map 0:a? -c copy -movflags +faststart` into a temporary `.part.mp4` file. After the copy, FFmpeg does a second pass to move the index to the start of the file; progress sits at 100% during this step.
4. The result is verified (`moov` before `mdat`, duration within 1 second of the source) and renamed to the final name. Free disk space is checked before starting.

---

## Building the Standalone EXE

```powershell
pip install pyinstaller
pyinstaller --noconsole --onefile --name SceneTrim SceneTrim.py
```

PyInstaller bundles `fixer.py` automatically because it is a normal import. The result is:

```text
dist\SceneTrim.exe
```

`ffmpeg.exe` and `ffprobe.exe` must be placed **next to `SceneTrim.exe`**. Do not use `--add-binary` with `--onefile`: the files would be extracted to a temporary folder where the app does not look for them.

If your antivirus flags the one-file build, build with `--onedir` instead:

```powershell
pyinstaller --noconsole --onedir --name SceneTrim SceneTrim.py
```

---

## Packaging for Distribution

To prepare a portable release bundle:

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

Use real `ffmpeg.exe` / `ffprobe.exe` files (for example from the Gyan.dev "essentials" build), not WinGet shortcut links.

---

## Project Structure

```text
SceneTrim/
├── SceneTrim.py        # Main application: GUI (Cutter + Fixer tabs) and cutting logic
├── fixer.py            # MP4 faststart detector/fixer (used by the GUI, also a CLI)
├── README.md           # Project documentation
└── .gitignore          # Git ignore rules
```

Suggested `.gitignore`:

```gitignore
dist/
build/
*.spec
ffmpeg.exe
ffprobe.exe
__pycache__/
.venv/
SceneTrim_release/
SceneTrim_release.zip
```

---

## Troubleshooting & FAQ

### A video keeps "loading" on my phone

The `moov` atom is probably at the end of the file. Open the **Fixer** tab, add the file, click **Check All**, and if it shows `needs-fix`, click **Fix Needed**. Copy the `_fixed` file to the phone and play it from local storage. Videos produced by the Cutter already include faststart.

### Fixer shows `needs-reencode`

The video is not H.264 with `yuv420p` (for example 10-bit or 4:2:2). Remuxing alone cannot fix this; the file has to be re-encoded.

### "FFmpeg Not Found" or `[WinError 2] The system cannot find the file specified`

SceneTrim searches for `ffmpeg.exe` and `ffprobe.exe` in:

1. Environment variables `$env:FFMPEG` and `$env:FFPROBE`.
2. Next to `SceneTrim.exe` / `SceneTrim.py`.
3. The current working directory.
4. System `PATH`.

Place both files in the same folder as `SceneTrim.exe` to resolve this immediately.

### The output video was not shortened

Make sure the cut intervals are within the actual duration of the video. Ranges outside the duration are ignored, and if nothing needs cutting the original is copied.

### Processing is slower on some computers

With an NVIDIA GPU that supports NVENC, encoding is fast. Without one, SceneTrim falls back to `libx264` on the CPU, which gives high quality but takes longer.

---

Author: Baraa Hawamdeh
