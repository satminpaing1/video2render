# main.py
# Kaneki Downloader - Fixed for MP3 Conversion & Video Merging

import os
import uuid
import time
import glob
import shutil
import socket
import urllib.parse as ul
import requests
import yt_dlp

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, Response, FileResponse

# --- FFmpeg Loading ---
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
    print("static_ffmpeg loaded")
except Exception:
    print("static_ffmpeg not available - assuming system ffmpeg.")

# ----------------- App setup -----------------
app = FastAPI(title="Kaneki Downloader - Server Fix")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads") 
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ----------------- Cookie handling -----------------
COOKIE_ENV = os.environ.get("YOUTUBE_COOKIES", "")
COOKIE_FILE = os.path.join(BASE_DIR, "cookies.txt")

if COOKIE_ENV and COOKIE_ENV.strip():
    try:
        with open(COOKIE_FILE, "w", encoding="utf-8") as f:
            f.write(COOKIE_ENV)
    except Exception as e:
        print("Failed to write cookies:", e)

# ----------------- Common settings -----------------
AUDIO_ID = "mp3-best" 

COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.youtube.com/",
}

def ydl_base(extra: dict = None):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 120,
        "force_ipv4": True,
        "http_headers": COMMON_HEADERS,
        "nocheckcertificate": True,
        # FFmpeg location define လုပ်ပေးရန်လိုနိုင်သည်
        # "ffmpeg_location": "/usr/bin/ffmpeg", 
    }
    if os.path.exists(COOKIE_FILE):
        opts["cookiefile"] = COOKIE_FILE
    if extra:
        opts.update(extra)
    return opts

# ----------------- Utilities -----------------
def clean_url(url: str) -> str:
    # YouTube Cleaning
    if "youtube.com" in url or "youtu.be" in url:
        try:
            parsed = ul.urlparse(url)
            qs = ul.parse_qs(parsed.query)
            if "v" in qs and qs["v"]:
                return f"https://www.youtube.com/watch?v={qs['v'][0]}"
            if parsed.netloc.endswith("youtu.be"):
                return f"https://www.youtube.com/watch?v={parsed.path.lstrip('/')}"
        except:
            pass
    # Facebook and others return as is (yt-dlp handles them)
    return url

def cleanup_file(path: str):
    """ Background task to remove file after sending """
    try:
        if os.path.exists(path):
            os.remove(path)
            print(f"Cleaned up: {path}")
    except Exception as e:
        print(f"Error cleaning up {path}: {e}")

# ----------------- Formats endpoint -----------------
@app.get("/formats")
def formats(url: str):
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    url = clean_url(url)

    opts = ydl_base({"skip_download": True})
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        raw = info.get("formats", []) or []
        # Filter for video only formats to show resolutions
        heights = sorted({int(f["height"]) for f in raw if f.get("height") and f.get("vcodec") != "none"}, reverse=True)

        simplified = []
        if heights:
            simplified.append({"format_id": "v-auto", "label": "Auto (Best Quality)", "ext": "mp4"})
            for h in heights:
                simplified.append({"format_id": f"v-{h}", "label": f"{h}p", "ext": "mp4"})
        
        # Add MP3 Option
        simplified.append({"format_id": AUDIO_ID, "label": "MP3 (Audio Only)", "ext": "mp3"})

        return {"formats": simplified, "title": info.get("title"), "thumbnail": info.get("thumbnail")}
    except Exception as e:
        print("Format Error:", e)
        raise HTTPException(status_code=500, detail=str(e))

# ----------------- DOWNLOAD ENDPOINT (SERVER SIDE) -----------------
@app.get("/download")
def download(url: str, format_id: str, background_tasks: BackgroundTasks):
    """
    Downloads, Converts/Merges on server, and sends file to user.
    """
    if not url or not format_id:
        raise HTTPException(status_code=400, detail="Missing parameters")
    
    url = clean_url(url)
    filename_id = uuid.uuid4().hex
    # Temporary output template
    out_tmpl = os.path.join(DOWNLOAD_DIR, f"{filename_id}.%(ext)s")

    ydl_opts = {
        "outtmpl": out_tmpl,
        "restrictfilenames": True,
    }

    # Logic for Formats
    if format_id == AUDIO_ID:
        # MP3 Conversion Logic
        ydl_opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        })
        final_ext = "mp3"
    
    elif format_id.startswith("v-"):
        # Video Logic (Merge Video + Audio)
        try:
            if format_id == "v-auto":
                 # Downloads best video and best audio and merges them
                ydl_opts.update({"format": "bestvideo+bestaudio/best"})
            else:
                height = int(format_id.split("-")[1])
                # Download specific height + best audio
                ydl_opts.update({"format": f"bestvideo[height<={height}]+bestaudio/best"})
            
            ydl_opts.update({"merge_output_format": "mp4"}) # Force merge to mp4
            final_ext = "mp4"
            
        except:
            ydl_opts.update({"format": "bestvideo+bestaudio/best", "merge_output_format": "mp4"})
            final_ext = "mp4"
    else:
         # Fallback
        ydl_opts.update({"format": "best"})
        final_ext = "mp4"

    # Merge base options
    final_opts = ydl_base(ydl_opts)

    try:
        print(f"Downloading {url} as {format_id}...")
        with yt_dlp.YoutubeDL(final_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'video')
            
            # Sanitizing filename for browser download
            safe_title = "".join([c for c in title if c.isalnum() or c in " .-_"]).strip()
            download_filename = f"{safe_title}.{final_ext}"

        # Locate the downloaded file
        # yt-dlp might have changed the extension during conversion (e.g. webm -> mp3)
        expected_file = os.path.join(DOWNLOAD_DIR, f"{filename_id}.{final_ext}")
        
        # Sometimes ffmpeg adds mp3 but the original was webm, finding the file:
        found_files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{filename_id}*"))
        if not found_files:
            raise HTTPException(status_code=500, detail="File processing failed.")
        
        final_file_path = found_files[0]

        # Send file and delete after sending
        background_tasks.add_task(cleanup_file, final_file_path)
        
        return FileResponse(
            path=final_file_path,
            filename=download_filename,
            media_type="application/octet-stream"
        )

    except Exception as e:
        print("Download Error:", e)
        # Cleanup if error
        for f in glob.glob(os.path.join(DOWNLOAD_DIR, f"{filename_id}*")):
            os.remove(f)
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

# ----------------- Root -----------------
@app.get("/")
def root():
    return {"message": "Kaneki Downloader is Running"}
