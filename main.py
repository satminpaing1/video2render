# main.py
# Kaneki Downloader - cookies-enabled version
# Instructions:
# 1) Export your YouTube cookies as "cookies.txt" (Netscape format) from your browser.
# 2) In Render (or your host) add an Environment Secret named YOUTUBE_COOKIES
#    and paste the entire cookies.txt content as the value.
# 3) Deploy. The app will write /app/cookies.txt from the env var and use it for yt-dlp.
# 4) Endpoints: /nettest, /formats?url=..., /download?url=...&format_id=...

import os
import uuid
import time
import glob
import socket
import requests
import yt_dlp

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

# ---------- App setup ----------
app = FastAPI(title="Kaneki Downloader (cookies-enabled)")

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

AUDIO_ID = "audio_mp3"

# ---------- Cookie handling ----------
# Render/host: set YOUTUBE_COOKIES secret to the full cookies.txt content
COOKIE_PATH = os.path.join(BASE_DIR, "cookies.txt")
COOKIE_ENV = os.environ.get("YOUTUBE_COOKIES")

if COOKIE_ENV:
    try:
        with open(COOKIE_PATH, "w", encoding="utf-8") as f:
            f.write(COOKIE_ENV)
        print("Wrote cookies to", COOKIE_PATH)
    except Exception as e:
        print("Failed to write cookies:", e)
        COOKIE_PATH = None
else:
    COOKIE_PATH = COOKIE_PATH if os.path.exists(COOKIE_PATH) else None
    if not COOKIE_PATH:
        print("No YOUTUBE_COOKIES provided; proceeding without cookies (may be blocked by YouTube).")

# ---------- Utility: network diagnostic ----------
@app.get("/nettest")
def nettest():
    hosts = ["www.youtube.com", "www.google.com", "api.github.com"]
    dns_results = {}
    for h in hosts:
        try:
            addrs = socket.getaddrinfo(h, 443)
            dns_results[h] = {"resolved": True, "addresses": list({a[4][0] for a in addrs})}
        except Exception as e:
            dns_results[h] = {"resolved": False, "error": str(e)}
    http_results = {}
    urls = ["https://www.google.com", "https://www.youtube.com", "https://httpbin.org/ip"]
    for u in urls:
        try:
            r = requests.get(u, timeout=5)
            http_results[u] = {"ok": True, "status": r.status_code}
        except Exception as e:
            http_results[u] = {"ok": False, "error": str(e)}
    return JSONResponse({"dns": dns_results, "http": http_results})

# ---------- Formats endpoint ----------
@app.get("/formats")
def formats(url: str):
    if not url:
        raise HTTPException(400, "URL is required")

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "force_ipv4": True,
        "noplaylist": True,
        "extractor_args": {"youtube": {"player_client": ["android"]}},
        "socket_timeout": 30,
    }

    PROXY = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
    if PROXY:
        opts["proxy"] = PROXY

    # attach cookiefile if available
    if COOKIE_PATH and os.path.exists(COOKIE_PATH):
        opts["cookiefile"] = COOKIE_PATH

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        heights = set()
        for f in info.get("formats", []) or []:
            h = f.get("height")
            if h:
                try:
                    heights.add(int(h))
                except:
                    pass

        target = [2160, 1440, 1080, 720, 480, 360]
        out = []
        out.append({"format_id": "v-auto", "label": "Auto (Best)", "ext": "mp4"})
        for h in target:
            if h in heights:
                out.append({"format_id": f"v-{h}", "label": f"{h}p", "ext": "mp4"})
        out.append({"format_id": AUDIO_ID, "label": "MP3 (128kbps)", "ext": "mp3"})

        return {"formats": out}
    except Exception as e:
        msg = str(e)
        print("FORMAT ERROR:", msg)
        if "No address associated with hostname" in msg or "Name or service not known" in msg:
            return {"error": "DNS_ERROR", "detail": "Cannot reach YouTube from this runtime. Check /nettest."}
        # Specific yt-dlp message about login/cookies
        if "Sign in to confirm you're not a bot" in msg or "use --cookies" in msg.lower():
            return {"error": "COOKIES_REQUIRED", "detail": "YouTube requires login cookies. See README."}
        return {"formats": []}

# ---------- Find produced output ----------
def find_output(prefix, attempts=12, wait=0.3):
    for _ in range(attempts):
        files = glob.glob(os.path.join(DOWNLOAD_DIR, prefix + "*"))
        if files:
            files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            return files[0]
        time.sleep(wait)
    return None

# ---------- Download endpoint ----------
@app.get("/download")
def download(url: str, format_id: str):
    if not url or not format_id:
        raise HTTPException(400, "Missing parameters")

    uid = str(uuid.uuid4())[:8]
    prefix = f"kaneki_{uid}"
    outtmpl = os.path.join(DOWNLOAD_DIR, prefix + ".%(ext)s")

    opts = {
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "continuedl": True,
        "retries": 3,
        "socket_timeout": 180,
        "force_ipv4": True,
        "extractor_args": {"youtube": {"player_client": ["android"]}},
    }

    PROXY = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
    if PROXY:
        opts["proxy"] = PROXY

    if COOKIE_PATH and os.path.exists(COOKIE_PATH):
        opts["cookiefile"] = COOKIE_PATH

    # select format
    if format_id == "v-auto":
        opts["format"] = "bestvideo+bestaudio/best"
        opts["merge_output_format"] = "mp4"
    elif format_id.startswith("v-"):
        try:
            h = int(format_id.split("-")[1])
            opts["format"] = f"bestvideo[height<={h}]+bestaudio/best"
            opts["merge_output_format"] = "mp4"
        except:
            opts["format"] = "bestvideo+bestaudio/best"
            opts["merge_output_format"] = "mp4"
    elif format_id == AUDIO_ID:
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "128"
        }]
    else:
        opts["format"] = "best"

    try:
        print(f"Starting download uid={uid} url={url} format={format_id}")
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)

        produced = find_output(prefix)
        if not produced:
            # include small diagnostic if yt-dlp produced no file
            raise RuntimeError("Download finished but no output file found. Check yt-dlp logs above.")
        filename = os.path.basename(produced)
        return {
            "download_url": f"/files/{filename}",
            "filename": filename,
            "title": info.get("title"),
        }

    except yt_dlp.utils.DownloadError as e:
        print("yt-dlp DownloadError:", str(e))
        # Provide actionable message when cookies are required
        msg = str(e)
        if "Sign in to confirm you're not a bot" in msg or "use --cookies" in msg.lower():
            raise HTTPException(502, "COOKIES_REQUIRED: YouTube requires login cookies. Set YOUTUBE_COOKIES secret and redeploy.")
        raise HTTPException(status_code=500, detail=f"Download failed: {msg}")
    except Exception as e:
        msg = str(e)
        print("DOWNLOAD ERROR:", msg)
        if "No address associated with hostname" in msg:
            raise HTTPException(
                502,
                "DNS Error: runtime cannot access YouTube. Check /nettest or use a host with outbound network."
            )
        raise HTTPException(status_code=500, detail=f"Download Error: {msg}")
