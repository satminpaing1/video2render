import os
import uuid
import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# -----------------------------
# FFmpeg Loader (static_ffmpeg)
# -----------------------------
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
    print("static_ffmpeg loaded")
except Exception as e:
    print("static_ffmpeg failed:", e)

# -----------------------------
# Load Cookies From Environment
# -----------------------------
COOKIE_ENV = os.getenv("YOUTUBE_COOKIES", "").strip()
COOKIE_PATH = "/app/cookies.txt"

if COOKIE_ENV:
    with open(COOKIE_PATH, "w", encoding="utf-8") as f:
        f.write(COOKIE_ENV)
    print("Wrote cookies to /app/cookies.txt")
else:
    print("NO COOKIES FOUND — YouTube protected videos will FAIL.")

# -----------------------------
# FastAPI Setup
# -----------------------------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
app.mount("/files", StaticFiles(directory=DOWNLOAD_DIR), name="files")

SPECIAL_AUDIO = "bestaudio"


@app.get("/")
def home():
    return {"status": "online", "cookies": "loaded" if COOKIE_ENV else "missing"}


# -----------------------------
# FORMAT FETCHER
# -----------------------------
@app.get("/formats")
def get_formats(url: str):

    if not COOKIE_ENV:
        raise HTTPException(
            400,
            "COOKIES_REQUIRED: YouTube now blocks format fetch without cookies."
        )

    ydl_opts = {
        "quiet": True,
        "cookiefile": COOKIE_PATH,
        "skip_download": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "extractor_args": {"youtube": {"player_client": ["web"]}},
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = []
        for f in info.get("formats", []):
            if f.get("height") and f.get("vcodec") != "none":
                formats.append({
                    "format_id": f"{f['format_id']}",
                    "height": f["height"],
                    "ext": f.get("ext", "mp4"),
                    "label": f"{f['height']}p"
                })

        if not formats:
            raise Exception("NO_VIDEO_FORMATS")

        return {"formats": formats}

    except Exception as e:
        print("FORMAT ERROR:", e)
        raise HTTPException(500, "Failed to fetch formats")


# -----------------------------
# DOWNLOAD HANDLER
# -----------------------------
@app.get("/download")
def download(url: str, format_id: str):

    if not COOKIE_ENV:
        raise HTTPException(
            400,
            "COOKIES_REQUIRED: YouTube requires login cookies."
        )

    uid = uuid.uuid4().hex[:8]
    out_file = os.path.join(DOWNLOAD_DIR, f"{uid}.%(ext)s")

    ydl_opts = {
        "outtmpl": out_file,
        "cookiefile": COOKIE_PATH,
        "quiet": True,
        "nocheckcertificate": True,
        "noplaylist": True,
        "merge_output_format": "mp4",
        "extractor_args": {"youtube": {"player_client": ["web"]}},
    }

    # -------- VIDEO --------
    if format_id != SPECIAL_AUDIO:
        ydl_opts["format"] = format_id

    # -------- AUDIO --------
    else:
        ydl_opts["format"] = "bestaudio"
        ydl_opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "128",
        }]

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)

        final_name = os.path.basename(filename)
        return {
            "download_url": f"/files/{final_name}",
            "filename": final_name
        }

    except Exception as e:
        print("DOWNLOAD ERROR:", e)
        raise HTTPException(500, "Download failed")
