# main.py
# Kaneki Downloader - Cleaned, Fixes Resolution/MP3 Errors, Uses Direct Streaming

import os
import uuid
import time
import glob
import socket
import urllib.parse as ul
import requests
import yt_dlp

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, Response, RedirectResponse

# --- FFmpeg Loading ---
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
    print("static_ffmpeg loaded")
except Exception:
    print("static_ffmpeg not available - assuming system ffmpeg.")

# ----------------- App setup -----------------
app = FastAPI(title="Kaneki Downloader - Direct Stream")

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
app.mount("/files", StaticFiles(directory=DOWNLOAD_DIR), name="files")

# ----------------- Cookie handling -----------------
COOKIE_ENV = os.environ.get("YOUTUBE_COOKIES", "")
COOKIE_FILE = os.path.join(BASE_DIR, "cookies.txt")

if COOKIE_ENV and COOKIE_ENV.strip():
    stripped = COOKIE_ENV.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        print("WARNING: YOUTUBE_COOKIES appears to be JSON. yt-dlp expects Netscape 'cookies.txt' format.")
    try:
        with open(COOKIE_FILE, "w", encoding="utf-8") as f:
            f.write(COOKIE_ENV)
        print("Wrote cookies to", COOKIE_FILE)
    except Exception as e:
        print("Failed to write cookies:", e)
else:
    if os.path.exists(COOKIE_FILE):
        print("Using existing cookies file at", COOKIE_FILE)
    else:
        print("No YOUTUBE_COOKIES provided. Running without cookies.")
    
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
    }
    if os.path.exists(COOKIE_FILE):
        opts["cookiefile"] = COOKIE_FILE # Cookies are included here!
    if extra:
        opts.update(extra)
    return opts

# ----------------- Utilities -----------------
def clean_youtube_url(url: str) -> str:
    """ Convert playlist/mix/watch?urls into a canonical watch?v=VIDEO_ID URL (if possible). """
    try:
        parsed = ul.urlparse(url)
        qs = ul.parse_qs(parsed.query)
        if "v" in qs and qs["v"]:
            vid = qs["v"][0]
            return f"https://www.youtube.com/watch?v={vid}"
        if parsed.netloc.endswith("youtu.be"):
            vid = parsed.path.lstrip("/")
            if vid:
                return f"https://www.youtube.com/watch?v={vid}"
    except Exception:
        pass
    return url

# ----------------- Root and HEAD for health checks -----------------
@app.get("/", include_in_schema=False)
def root():
    return {"status": "ok", "message": "Kaneki Downloader (Direct Stream)"}

@app.head("/", include_in_schema=False)
def head_root():
    return Response(status_code=200)

# ----------------- Nettest (diagnostic) -----------------
@app.get("/nettest")
def nettest():
    hosts = ["www.youtube.com", "www.google.com", "api.github.com"]
    dns = {}
    for h in hosts:
        try:
            addrs = socket.getaddrinfo(h, 443)
            dns[h] = {"ok": True, "addresses": list({a[4][0] for a in addrs})}
        except Exception as e:
            dns[h] = {"ok": False, "error": str(e)}
    http = {}
    for u in ["https://www.google.com", "https://www.youtube.com", "https://httpbin.org/ip"]:
        try:
            r = requests.get(u, timeout=6, headers=COMMON_HEADERS)
            http[u] = {"ok": True, "status": r.status_code}
        except Exception as e:
            http[u] = {"ok": False, "error": str(e)}
    return JSONResponse({"dns": dns, "http": http})

# ----------------- Formats endpoint -----------------
@app.get("/formats")
def formats(url: str):
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    url = clean_youtube_url(url)

    opts = ydl_base({"skip_download": True})
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        raw = info.get("formats", []) or []
        # FIX: Ensure height is an int and filter formats with video streams (Resolution Fix)
        heights = sorted({int(f["height"]) for f in raw if f.get("height") and f.get("vcodec") != "none"}, reverse=True)

        simplified = []
        
        if heights:
            simplified.append({"format_id": "v-auto", "label": "Auto (best)", "ext": "mp4"})
            for h in heights:
                # FIX: Resolution numbers are correctly included (e.g., "720p")
                simplified.append({"format_id": f"v-{h}", "label": f"{h}p", "ext": "mp4"})
        
        # Audio alias
        audio_exists = any((f.get("acodec") and f.get("vcodec") == "none") for f in raw)
        if audio_exists:
            # MP3 Fix: Use the correct AUDIO_ID
            simplified.append({"format_id": AUDIO_ID, "label": "MP3 (bestaudio)", "ext": "mp3"})

        # Sample of raw formats (for advanced selection)
        raw_sample = []
        for f in raw[:40]:
            raw_sample.append({
                "format_id": f.get("format_id"),
                "ext": f.get("ext"),
                "height": f.get("height"),
                "vcodec": f.get("vcodec"),
                "acodec": f.get("acodec"),
                "abr": f.get("abr"),
                "tbr": f.get("tbr"),
                "filesize": f.get("filesize") or f.get("filesize_approx")
            })

        return {"formats": simplified, "raw_formats_sample": raw_sample, "title": info.get("title")}
    except Exception as e:
        msg = str(e)
        print("FORMAT ERROR:", msg)
        if "No address associated with hostname" in msg:
            raise HTTPException(status_code=502, detail="DNS Error: Cannot reach YouTube. Check /nettest.")
        if "Sign in to confirm you're not a bot" in msg or "use --cookies" in msg.lower():
            # This error suggests the cookies are NOT working or expired
            raise HTTPException(status_code=502, detail="COOKIES_REQUIRED: YouTube requires login cookies. Please check your YOUTUBE_COOKIES value.")
        raise HTTPException(status_code=500, detail="Failed to fetch formats")

# ----------------- DIRECT STREAMING/DOWNLOAD ENDPOINT (FASTEST METHOD) -----------------
@app.get("/download")
def download(url: str, format_id: str):
    """
    Extracts the final streaming URL and redirects the user's browser to it. 
    This is the fastest method (instant start).
    """
    if not url or not format_id:
        raise HTTPException(status_code=400, detail="Missing parameters")
    url = clean_youtube_url(url)

    # 1. Determine the format expression
    if format_id == "v-auto":
        format_expr = "bestvideo+bestaudio/best"
    # MP3 Fix: Ensure AUDIO_ID is correctly checked and assigned the right expression
    elif format_id == AUDIO_ID: 
        format_expr = "bestaudio/best"
    elif format_id.startswith("v-"):
        try:
            req_h = int(format_id.split("-")[1])
            format_expr = f"bestvideo[height<={req_h}]+bestaudio/best"
        except Exception:
            format_expr = "bestvideo+bestaudio/best"
    else:
        format_expr = format_id

    # 2. Configure yt-dlp to only simulate and get the URL
    opts = ydl_base({
        "format": format_expr, 
        "skip_download": True, # CRUCIAL: Don't download on server
        "simulate": True,      # CRUCIAL: Get final URL
        "nocheckcertificate": True,
    })
    
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            # download=False returns the final stream URL in info['url']
            info = ydl.extract_info(url, download=False)

        final_url = info.get("url")

        if final_url:
            print(f"Redirecting user to stream URL: {final_url}")
            # 3. Redirect the user's browser to the original YouTube/CDN stream URL
            return RedirectResponse(url=final_url, status_code=302)
        else:
            raise RuntimeError("Failed to extract final streaming URL. Source may be unavailable.")

    except Exception as e:
        msg = str(e)
        print("STREAM URL ERROR:", msg)
        if "Sign in to confirm you're not a bot" in msg or "use --cookies" in msg.lower():
            raise HTTPException(status_code=502, detail="COOKIES_REQUIRED: YouTube requires login cookies. Please check your YOUTUBE_COOKIES value.")
        if "Requested format is not available" in msg:
            raise HTTPException(status_code=400, detail="FORMAT_NOT_AVAILABLE: Requested format isn't available. Try 'v-auto'.")
        raise HTTPException(status_code=500, detail=f"Streaming failed: {msg}")
