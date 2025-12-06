import os
import uuid
import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response

# --------------------------------------------------------------
# FFmpeg PATH (static-ffmpeg)
# --------------------------------------------------------------
import static_ffmpeg
static_ffmpeg.add_paths()

app = FastAPI()

# --------------------------------------------------------------
# CORS
# --------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------
# DIRECTORIES
# --------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app.mount("/files", StaticFiles(directory=DOWNLOAD_DIR), name="files")

# --------------------------------------------------------------
# COOKIE FILE HANDLING
# --------------------------------------------------------------

COOKIE_ENV = os.getenv("YOUTUBE_COOKIES", "")
COOKIE_FILE = os.path.join(BASE_DIR, "cookies.txt")

if COOKIE_ENV.strip():
    try:
        with open(COOKIE_FILE, "w", encoding="utf-8") as f:
            f.write(COOKIE_ENV.strip())
        print("Wrote cookies to /app/cookies.txt")
    except:
        print("Failed to write cookie file.")
else:
    print("No YOUTUBE_COOKIES provided. Running without cookies.")

# --------------------------------------------------------------
# YDL BASE OPTIONS
# --------------------------------------------------------------

def ydl_base(extra=None):
    opts = {
        "quiet": True,
        "nocheckcertificate": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "cookiefile": COOKIE_FILE if os.path.exists(COOKIE_FILE) else None,
        "extractor_args": {"youtube": {"player_client": ["android"]}},
        "force_ipv4": True,
    }
    if extra:
        opts.update(extra)
    return opts

# Audio simplified ID
AUDIO_ID = "audio_mp3"


# --------------------------------------------------------------
@app.get("/")
def root():
    return {"status": "ok", "message": "Kaneki Downloader V3 — Full Fixed Version"}


# HEAD for Render health check
@app.head("/", include_in_schema=False)
def head_root():
    return Response(status_code=200)


# --------------------------------------------------------------
# 1. FETCH AVAILABLE FORMATS
# --------------------------------------------------------------
@app.get("/formats")
def formats(url: str):
    try:
        opts = ydl_base({"skip_download": True})
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(url, download=False)

        raw = info.get("formats", [])
        heights = sorted({int(f["height"]) for f in raw if f.get("height") and f.get("vcodec") != "none"}, reverse=True)

        out = []
        for h in heights:
            out.append({
                "format_id": f"v-{h}",
                "label": f"{h}p",
                "height": h,
                "ext": "mp4"
            })

        # auto video
        if "v-720" in [f["format_id"] for f in out]:
            out.insert(0, {"format_id": "v-auto", "label": "Auto (Best MP4)", "ext": "mp4"})

        # audio
        out.append({"format_id": AUDIO_ID, "label": "MP3 Audio", "ext": "mp3"})

        return {"formats": out}

    except Exception as e:
        print("Format Error:", e)
        raise HTTPException(status_code=500, detail="Failed to fetch formats")


# --------------------------------------------------------------
# 2. DOWNLOAD + FORMAT AUTO-FALLBACK
# --------------------------------------------------------------
@app.get("/download")
def download(url: str, format_id: str):

    if not url:
        raise HTTPException(status_code=400, detail="Missing URL")

    try:
        uid = str(uuid.uuid4())[:8]
        prefix = f"kaneki_{uid}"
        outtmpl = os.path.join(DOWNLOAD_DIR, prefix + ".%(ext)s")

        # First: probe video formats
        probe_opts = ydl_base({"skip_download": True})
        with yt_dlp.YoutubeDL(probe_opts) as probe:
            info = probe.extract_info(url, download=False)

        raw_formats = info.get("formats", [])
        available_heights = sorted({
            int(f["height"]) for f in raw_formats 
            if f.get("height") and f.get("vcodec") != "none"
        }, reverse=True)

        # ------------------------------------------------------
        # FORMAT DECISION
        # ------------------------------------------------------
        final_format = None

        # simplified video id
        if format_id.startswith("v-"):
            req = int(format_id.split("-")[1])
            chosen = None
            for h in available_heights:
                if h <= req:
                    chosen = h
                    break
            if not chosen and available_heights:
                chosen = min(available_heights)

            final_format = f"bestvideo[height<={chosen}]+bestaudio/best"

        # auto
        elif format_id == "v-auto":
            final_format = "bestvideo+bestaudio/best"

        # audio
        elif format_id == AUDIO_ID:
            final_format = "bestaudio/best"

        # fallback
        else:
            final_format = "bestvideo+bestaudio/best"

        # ------------------------------------------------------
        # FINAL DOWNLOAD OPTIONS
        # ------------------------------------------------------
        dl_opts = ydl_base({
            "outtmpl": outtmpl,
            "format": final_format,
            "retries": 3,
            "continuedl": True,
        })

        if format_id == AUDIO_ID:
            dl_opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "128",
            }]

        print(f"Downloading with format expr: {final_format}")

        with yt_dlp.YoutubeDL(dl_opts) as y:
            info2 = y.extract_info(url, download=True)

        # Find produced output
        for f in os.listdir(DOWNLOAD_DIR):
            if f.startswith(prefix):
                return {
                    "download_url": f"/files/{f}",
                    "filename": f,
                    "title": info2.get("title", "Unknown Title")
                }

        raise RuntimeError("No output file generated")

    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        print("yt-dlp ERROR:", msg)

        if "Sign in to confirm you're not a bot" in msg:
            raise HTTPException(status_code=403, detail="COOKIE_REQUIRED: Must add YouTube cookies")

        if "format is not available" in msg:
            raise HTTPException(status_code=400, detail="FORMAT_NOT_AVAILABLE")

        raise HTTPException(status_code=500, detail=f"Download failed: {msg}")

    except Exception as e:
        print("Download Error:", e)
        raise HTTPException(status_code=500, detail=f"Error: {e}")
