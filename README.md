# AI-Powered Video Fixer for Windows

[![Platform](https://img.shields.io/badge/Platform-Windows-blue.svg)](https://microsoft.com/windows)
[![Python](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](https://www.python.org/)
[![GUI](https://img.shields.io/badge/GUI-FreeSimpleGUI-orange.svg)](https://github.com/spyoungtech/FreeSimpleGUI)
[![Engine](https://img.shields.io/badge/Engine-FFmpeg%209.0-red.svg)](https://ffmpeg.org/)
[![AI](https://img.shields.io/badge/AI-Google%20Gemini-blueviolet.svg)](https://aistudio.google.com/)

A reliable, AI-assisted video inspection, repair, and transcoding desktop application and CLI for Windows. It identifies container faults (such as the MP4 `moov` atom placed after `mdat`, causing endless buffering on mobile phones), detects codec and pixel format incompatibilities (HEVC, 10-bit color, unsupported audio tracks), and repairs or converts media files safely without overwriting source files.

Powered by Google's official **Gemini API** (`google-genai` SDK) for intelligent diagnostics, the application features deterministic fallback logic so it functions seamlessly offline or without an API key.

---

## Table of Contents

1. [Features](#features)
2. [Remuxing vs. Transcoding](#remuxing-vs-transcoding)
3. [System Requirements](#system-requirements)
4. [Installation & Python Setup](#installation--python-setup)
5. [FFmpeg & FFprobe Setup](#ffmpeg--ffprobe-setup)
6. [Gemini API Configuration & Security](#gemini-api-configuration--security)
7. [Running in Development](#running-in-development)
   - [Desktop GUI (`app.py`)](#desktop-gui-apppy)
   - [Command-Line Interface (`fixer.py`)](#command-line-interface-fixerpy)
8. [Automated Testing](#automated-testing)
9. [Packaging Standalone Windows Executable](#packaging-standalone-windows-executable)
10. [AI Recommendations & Safety Verification](#ai-recommendations--safety-verification)
11. [Troubleshooting & FAQ](#troubleshooting--faq)
12. [Licensing & Distribution Considerations](#licensing--distribution-considerations)

---

## Features

- **Automated MP4 Atom Scanning**: Directly parses MP4 container atoms (`top_level_atoms`) to verify if the index (`moov`) appears before the media data (`mdat`) for fast-start mobile streaming.
- **Deep Technical Inspection**: Uses FFprobe to extract full video parameters (codec, profile, level, dimensions, frame rate, pixel format, 10-bit/HDR transfer characteristics), audio layouts (codecs, channels, sample rate), and subtitle streams.
- **Intelligent Classification**: Distinguishes between `ok` (compatible), `needs-remux` (container or faststart fix only), `needs-transcode` (codec or color format incompatible), `corrupt` (unreadable packets/header), and `unknown`.
- **Google Gemini 2.5 Integration**: Uses Google's modern `google-genai` SDK with strict JSON schemas to provide human-readable diagnostics and recommendations.
- **Hard Safety Guardrails**: AI recommendations are strictly validated locally against deterministic technical constraints. Gemini is never permitted to execute arbitrary shell commands, invent metadata, override corruption detections, or downgrade required transcodes.
- **Zero Quality-Loss Remuxing**: Whenever streams already match the target profile, stream copying (`-c copy`) is used with `-movflags +faststart`.
- **High-Quality Compatible Transcoding**: Safe CRF-based software encoding (`libx264` + `aac`) ensures 100% playback compatibility across iOS, Android, and web media players.
- **Multi-Stage Output Verification**: Confirms file non-emptiness, verifies metadata, tests duration tolerance, and executes an FFmpeg null-mux decode test (`-f null -`) to prove stream integrity.
- **Source File Safety**: Never overwrites source files. Writes to atomic temporary parts (`.part_<uuid>.mp4`) and replaces only on complete verification pass.
- **Responsive GUI**: Built with FreeSimpleGUI; background operations run in isolated worker threads with cancellation and live progress reporting.

---

## Remuxing vs. Transcoding

Understanding the difference between **Remuxing** and **Transcoding** is critical to efficient video processing:

| Feature | Remuxing (`-c copy`) | Transcoding (`libx264` / `aac`) |
| :--- | :--- | :--- |
| **Operation** | Copies compressed video and audio packets directly into a new container without decoding. | Decompresses every video/audio frame and re-encodes it into a compatible codec. |
| **Speed** | Extremely fast (limited only by disk read/write speed, typically 100-500+ MB/s). | Slower (CPU/GPU compute intensive, typically real-time to 5x speed). |
| **Quality** | **100% Lossless**. The video data is bit-for-bit identical to the source. | Slight generational loss depending on CRF quality settings. |
| **When Used** | When streams are already compatible (e.g. H.264 8-bit, AAC), but the MP4 index (`moov`) is misplaced, or container is MKV/MOV. | When the codec (e.g. HEVC/H.265, AV1, VP9), pixel format (10-bit `yuv420p10le`), or audio format is incompatible with target devices. |

The application's deterministic analyzer always chooses **Remuxing** whenever safe, avoiding unnecessary transcoding to preserve time and quality.

---

## System Requirements

- **Operating System**: Windows 10 or Windows 11 (64-bit).
- **Python**: Python 3.10 to 3.13 (for development from source).
- **Disk Space**: At least 500 MB free space for the application and temporary conversion files.
- **FFmpeg**: FFmpeg 5.0+ and FFprobe (bundled automatically in the release package).

---

## Installation & Python Setup

1. **Clone or Download the Repository**:
   ```pwsh
   cd C:\Users\HP\Desktop\PySimpleGUI-Project
   ```

2. **Create and Activate Virtual Environment**:
   ```pwsh
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. **Install Dependencies**:
   ```pwsh
   pip install -r requirements.txt
   ```

---

## FFmpeg & FFprobe Setup

The application automatically locates `ffmpeg` and `ffprobe` in the following order:
1. Environment variables `FFMPEG` and `FFPROBE` (if set to valid file paths).
2. Directly next to the running executable or script.
3. In an `assets/bin/` subfolder.
4. Current working directory.
5. System `PATH`.

To verify your system FFmpeg installation:
```pwsh
ffmpeg -version
ffprobe -version
```

If not installed, download the official Windows build from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) or install via winget:
```pwsh
winget install Gyan.FFmpeg
```

---

## Gemini API Configuration & Security

The application supports AI diagnostics powered by Google Gemini.

1. **Get an API Key**:
   Visit [Google AI Studio](https://aistudio.google.com/) and create a free API key.

2. **Configure `.env`**:
   Copy `.env.example` to `.env` in the project root (or next to `VideoFixer.exe` in the release folder):
   ```env
   GEMINI_API_KEY=your_actual_api_key_here
   GEMINI_MODEL=gemini-2.5-flash
   AI_ENABLED=true
   ```

### API Security Considerations
> [!IMPORTANT]
> - An external `.env` file is intended for personal and local workstation usage.
> - **Never** commit `.env` into source control (it is ignored in `.gitignore`).
> - Storing an API key in `.env` next to a distributed executable does **not** protect the key from extraction if shared with third parties.
> - If distributing the application publicly, leave `GEMINI_API_KEY` blank and instruct users to provide their own personal API key in their local `.env`.
> - If no key is provided, the application automatically switches to deterministic local analysis without failing.

---

## Running in Development

### Desktop GUI (`app.py`)
Launch the interactive graphical interface:
```pwsh
.\.venv\Scripts\python.exe app.py
```
- **Add Files / Add Folder**: Load files into the batch table.
- **Inspect Files**: Probes all files and displays status, resolution, codecs, duration, and recommended action.
- **Start Processing**: Executes remuxing or transcoding with live progress bar and non-blocking background threads.
- **Cancel**: Gracefully terminates running FFmpeg subprocesses and cleans up partial files.
- **Open Output Folder**: Opens the target destination directory in Windows Explorer.

### Command-Line Interface (`fixer.py`)
The CLI is fully backward compatible with scripts and external automation.

```pwsh
# Quick check of files without processing
python fixer.py "C:\Videos\clip1.mp4" --check-only

# Fix all files in a folder and write to a fixed directory
python fixer.py "C:\Videos" --outdir "C:\Videos\repaired" --suffix _fixed

# Use Gemini AI diagnostics
python fixer.py "C:\Videos\clip1.mp4" --ai

# Select a specific profile
python fixer.py "C:\Videos\clip1.mp4" --profile high_quality_h264
```

---

## Automated Testing

The project includes a comprehensive test suite in `tests/` covering media probing, classification, remuxing, transcoding, verification, AI schema validation, safety overrides, and Unicode path handling.

Synthetic media fixtures are generated dynamically via FFmpeg without relying on external copyrighted media.

Run the test suite with:
```pwsh
.\.venv\Scripts\pytest.exe -v
```

---

## Packaging Standalone Windows Executable

The application includes an automated build script `build_exe.py` that utilizes PyInstaller to generate a self-contained release package:

```pwsh
.\.venv\Scripts\python.exe build_exe.py
```

### Build Output Structure
The compiled package is placed in `dist/VideoFixer/`:
```text
dist/VideoFixer/
├── VideoFixer.exe          # Standalone Windows GUI executable
├── ffmpeg.exe              # Bundled FFmpeg binary
├── ffprobe.exe             # Bundled FFprobe binary
├── .env.example            # Configuration template
└── _internal/              # Packaged Python runtimes and libraries
```

When frozen, `VideoFixer.exe` automatically looks for `.env`, `ffmpeg.exe`, and `ffprobe.exe` right next to itself in its base folder.

---

## AI Recommendations & Safety Verification

### How AI Recommendations are Validated
1. **Privacy-Conscious Input**: Only technical stream metadata (codec name, resolution, audio channels, durations, atom status) is transmitted to the Gemini API. File paths, names, and video contents are never uploaded.
2. **Strict Schema**: Responses are constrained via Pydantic to a schema containing `action` (`no_action`, `remux`, `transcode`, `manual_review`), `confidence` (0.0 to 1.0), and `reasoning`.
3. **Hard Local Constraints**:
   - If deterministic inspection detects file corruption, AI cannot downgrade it to `no_action` or `remux`.
   - If video codec or pixel format is incompatible (e.g. HEVC or 10-bit), AI cannot force `remux` or `no_action`.
   - If AI confidence is below 60%, deterministic fallback rules prevail.

### Multi-Stage Verification Pipeline
Before any processed file is finalized:
1. **File Existence & Size**: Ensures output exists and exceeds minimum byte threshold.
2. **Container Fast-Start**: Validates top-level atoms to guarantee `moov` precedes `mdat`.
3. **Stream Parity**: Probes output to confirm video and audio streams match target requirements.
4. **Duration Tolerance**: Checks output duration matches source duration within $\pm 1.5\text{s}$.
5. **Decode Null-Mux Test**: Runs `ffmpeg -v error -i <output> -t 10 -f null -` to verify frames decode cleanly without corruption.
6. **Atomic Move**: Only after all checks pass is the temporary `.part` file moved into place.

---

## Troubleshooting & FAQ

### 1. `ffprobe executable not found or not configured`
Ensure `ffmpeg` and `ffprobe` are on your system `PATH` or placed directly in the same folder as `VideoFixer.exe` / `fixer.py`.

### 2. `GEMINI_API_KEY is not configured in .env`
The application will operate normally in local deterministic mode. If you want AI explanations, copy `.env.example` to `.env` next to the executable and paste your key.

### 3. API Quota Exceeded or Network Error
If the Gemini API reaches rate limits or network is unavailable, the application gracefully continues using local deterministic rules without interruption.

### 4. Closed Captions or Bitmap Subtitles Dropped
MP4 containers only support text-based subtitles via the `mov_text` format. Bitmap subtitles (such as PGS from Blu-rays or VobSub from DVDs) cannot be stored in standard MP4 containers and are safely bypassed to prevent muxer crashes.

---

## Licensing & Distribution Considerations

- **FFmpeg**: FFmpeg is licensed under the GNU Lesser General Public License (LGPL) version 2.1 or later (or GPL depending on enabled options like `libx264`). When distributing FFmpeg binaries alongside your application:
  - Do not link FFmpeg statically into proprietary code; invoke it as a separate external subprocess (as implemented here).
  - Include FFmpeg's license documentation and attribution in your release package.
- **SceneTrim & VideoFixer**: Project code is provided for video editing and repair workflows under standard open-source terms.
