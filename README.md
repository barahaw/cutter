# Bhw_cutter_gui

A desktop tool with a FreeSimpleGUI interface that removes unwanted sections from videos using FFmpeg. It encodes on the GPU with `h264_nvenc` when available and falls back to the CPU (`libx264`) automatically.

## Requirements

- Windows
- Python 3.10+
- FFmpeg (including `ffprobe`)

## Install FFmpeg

```powershell
winget install Gyan.FFmpeg
```

Close **all** terminal and editor windows, open a new PowerShell, and verify:

```powershell
ffmpeg -version
ffprobe -version
```

If they are still not found, set the paths manually for the current session:

```powershell
$env:FFMPEG  = "C:\path\to\ffmpeg\bin\ffmpeg.exe"
$env:FFPROBE = "C:\path\to\ffmpeg\bin\ffprobe.exe"
```

## Run

```powershell
cd C:\Users\HP\Desktop\Bhw_cutter_gui
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install FreeSimpleGUI
python Bhw_cutter_gui.py
```

## Usage

1. Choose the **Input Folder** (your videos) and the **Output Folder**.
2. Paste one block per video into the text box:

```
E01
29:32-30:17
44:22-45:15

E02
clear
```

3. Click **Run Cutter**.

Rules:

- The first line of each block is the video file name **without the extension** (`E01` matches `E01.mp4`, `E01.mkv`, ...).
- Each `start-end` line is a section that will be **removed**.
- Time formats: `SS`, `MM:SS`, or `HH:MM:SS`.
- `clear` means no cuts; the file is copied as is.
- Times must be inside the video's duration, otherwise they are ignored.
- Separate blocks with a blank line.

## Troubleshooting

**`[WinError 2] The system cannot find the file specified` / "FFmpeg Not Found"**
Python cannot find `ffmpeg.exe` or `ffprobe.exe`. Install FFmpeg, open a new terminal, and check `ffmpeg -version`. Or set `$env:FFMPEG` and `$env:FFPROBE`, or place both `.exe` files next to the script.

**The output video was not shortened**
The times you entered are outside the video's length (for example `29:32` in a 2-minute video). Check the video duration and use times within it.

**`Unable to parse "rc" option value "vbr_hq"`**
Newer FFmpeg versions removed `vbr_hq`. Use this in the script:

```python
NVENC_RATECTRL = ["-rc", "vbr", "-tune", "hq", "-cq", "19", "-b:v", "0"]
```

**Processing is slow**
If the GPU encoder fails or no NVIDIA GPU is present, the tool uses CPU encoding (`libx264`), which is much slower.

## Build an EXE (optional)

```powershell
pip install pyinstaller
pyinstaller --noconsole --onefile Bhw_cutter_gui.py
```

Place `ffmpeg.exe` and `ffprobe.exe` in the same folder as the generated EXE.

---

Author: Baraa Hawamdeh
