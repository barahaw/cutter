#!/usr/bin/env python3
"""
fixer.py - detect MP4 files whose index (moov) is at the end and remux them
with +faststart (no re-encoding), so phones start playback immediately.

CLI:
    python fixer.py E04.mp4 E18.mp4
    python fixer.py "C:\\Videos" --outdir "C:\\Videos\\fixed" --suffix _fixed
    python fixer.py E04.mp4 --check-only

From the GUI (worker thread):
    from fixer import fix_faststart, check_file
"""

import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
from typing import Callable, Dict, List, Optional, Tuple

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
VIDEO_EXTS = {".mp4", ".m4v", ".mov"}


def find_binary(name: str) -> Optional[str]:
    base = os.path.dirname(sys.executable if getattr(sys, "frozen", False)
                           else os.path.abspath(__file__))
    exe = f"{name}.exe" if sys.platform == "win32" else name
    local = os.path.join(base, exe)
    return local if os.path.isfile(local) else shutil.which(name)


FFMPEG = find_binary("ffmpeg")
FFPROBE = find_binary("ffprobe")


# ---------------- Atom scanning (no ffmpeg needed) ----------------

def top_level_atoms(path: str) -> List[Tuple[str, int, int]]:
    """Return [(name, offset, size)] for top-level MP4 atoms. Reads headers only."""
    atoms = []
    file_size = os.path.getsize(path)
    with open(path, "rb") as f:
        pos = 0
        while pos + 8 <= file_size:
            f.seek(pos)
            header = f.read(8)
            if len(header) < 8:
                break
            size, name = struct.unpack(">I4s", header)
            if size == 1:                      # 64-bit size follows
                size = struct.unpack(">Q", f.read(8))[0]
            elif size == 0:                    # atom runs to end of file
                size = file_size - pos
            if size < 8:                       # corrupt header, stop
                break
            atoms.append((name.decode("latin-1"), pos, size))
            pos += size
    return atoms


def has_faststart(path: str) -> Optional[bool]:
    """True if moov comes before mdat, False if after, None if unknown."""
    moov = mdat = None
    for name, offset, _ in top_level_atoms(path):
        if name == "moov" and moov is None:
            moov = offset
        elif name == "mdat" and mdat is None:
            mdat = offset
    if moov is None or mdat is None:
        return None
    return moov < mdat


# ---------------- ffprobe ----------------

def probe(path: str) -> Dict:
    """Return duration, video info, audio presence and caption-stream count."""
    if not FFPROBE:
        raise RuntimeError("ffprobe not found")
    res = subprocess.run(
        [FFPROBE, "-v", "error", "-print_format", "json",
         "-show_streams", "-show_format", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=CREATE_NO_WINDOW)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or "ffprobe failed")
    data = json.loads(res.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    return {
        "duration": float(data.get("format", {}).get("duration") or 0.0),
        "vcodec": video.get("codec_name"),
        "profile": video.get("profile"),
        "pix_fmt": video.get("pix_fmt"),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "extra_streams": sum(1 for s in streams
                             if s.get("codec_type") not in ("video", "audio")),
    }


def phone_compatible(info: Dict) -> bool:
    return (info["vcodec"] == "h264"
            and info["pix_fmt"] == "yuv420p"
            and (info["profile"] or "").split()[0] in
            ("Baseline", "Constrained", "Main", "High"))


def check_file(path: str) -> Dict:
    """Quick status for the GUI list."""
    info = probe(path)
    fast = has_faststart(path)
    if fast is None:
        status = "unknown"
    elif fast:
        status = "ok" if phone_compatible(info) else "needs-reencode"
    else:
        status = "needs-fix"
    return {"status": status, "faststart": fast, **info}


# ---------------- Fix ----------------

def fix_faststart(src: str, dst: str,
                  on_progress: Optional[Callable[[float], None]] = None,
                  cancel: Callable[[], bool] = lambda: False,
                  on_process: Optional[Callable[["subprocess.Popen"], None]] = None) -> bool:
    """Remux src -> dst with +faststart. Video + audio only (drops c608/subtitle
    streams). Writes to a temp file first and renames only on success.

    on_process(proc) is called immediately after the Popen starts, before
    reading stdout. Use it to register the process for external cancellation.
    """
    if not FFMPEG:
        raise RuntimeError("ffmpeg not found")
    info = probe(src)
    total = info["duration"] or 0.0

    out_dir = os.path.dirname(os.path.abspath(dst))
    os.makedirs(out_dir, exist_ok=True)
    need = os.path.getsize(src) * 1.05
    if shutil.disk_usage(out_dir).free < need:
        raise RuntimeError("Not enough free disk space for the output file")

    tmp = dst + ".part.mp4"
    cmd = [FFMPEG, "-y", "-nostdin", "-v", "error", "-nostats",
           "-progress", "pipe:1",
           "-i", src, "-map", "0:v", "-map", "0:a?",
           "-c", "copy", "-movflags", "+faststart", tmp]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace",
                            creationflags=CREATE_NO_WINDOW)

    # Notify caller about the Popen object so it can register it for kill.
    if on_process is not None:
        on_process(proc)

    try:
        for line in proc.stdout:
            if cancel():
                proc.kill()
                break
            if line.startswith(("out_time_us=", "out_time_ms=")) and total > 0 and on_progress:
                try:
                    secs = int(line.split("=")[1]) / 1_000_000
                    on_progress(min(secs / total, 1.0))
                except ValueError:
                    pass
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()

    ok = proc.returncode == 0 and os.path.exists(tmp)
    if ok and not cancel():
        ok = verify(src, tmp)
    if ok and not cancel():
        os.replace(tmp, dst)
        if on_progress:
            on_progress(1.0)
        return True
    if os.path.exists(tmp):
        os.remove(tmp)
    return False


def verify(src: str, out: str, tolerance: float = 1.0) -> bool:
    """moov must be first and duration must match the source."""
    if has_faststart(out) is not True:
        return False
    return abs(probe(src)["duration"] - probe(out)["duration"]) <= tolerance


# ---------------- CLI ----------------

def collect(paths: List[str]) -> List[str]:
    files = []
    for p in paths:
        if os.path.isdir(p):
            for name in sorted(os.listdir(p)):
                if os.path.splitext(name)[1].lower() in VIDEO_EXTS:
                    files.append(os.path.join(p, name))
        elif os.path.isfile(p):
            files.append(p)
    return files


def main():
    ap = argparse.ArgumentParser(description="Fix MP4 files for phone playback (faststart).")
    ap.add_argument("paths", nargs="+", help="files or folders")
    ap.add_argument("--outdir", help="output folder (default: next to source)")
    ap.add_argument("--suffix", default="_fixed")
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()

    if not FFMPEG or not FFPROBE:
        sys.exit("ffmpeg/ffprobe not found (PATH or next to fixer.py)")

    for src in collect(args.paths):
        try:
            info = check_file(src)
        except Exception as e:
            print(f"[ERR ] {src}: {e}")
            continue
        print(f"[{info['status']:<13}] {os.path.basename(src)}  "
              f"({info['vcodec']}/{info['pix_fmt']}, {info['duration']:.0f}s)")
        if args.check_only or info["status"] != "needs-fix":
            continue
        stem, ext = os.path.splitext(os.path.basename(src))
        dst = os.path.join(args.outdir or os.path.dirname(os.path.abspath(src)),
                           f"{stem}{args.suffix}{ext}")
        ok = fix_faststart(
            src, dst,
            on_progress=lambda p: print(f"\r   {p*100:5.1f}%", end="", flush=True))
        print("\n   done ->" if ok else "\n   FAILED", dst if ok else "")


if __name__ == "__main__":
    main()
