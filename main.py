# main.py
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

app = FastAPI(title="Kaneki Downloader (Render)")

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


@app.get("/")
def home():
    return {"status": "ok", "message": "Kaneki Downloader (Render) Running"}


# Network diagnostic endpoint
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
    }

    PROXY = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
    if PROXY:
        opts["proxy"] = PROXY

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
        return {"formats": []}


def find_output(prefix):
    for _ in range(12):
        files = glob.glob(os.path.join(DOWNLOAD_DIR, prefix + "*"))
        if files:
            files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            return files[0]
        time.sleep(0.3)
    return None


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
        "socket_timeout": 120,
        "force_ipv4": True,
        "extractor_args": {"youtube": {"player_client": ["android"]}},
    }

    PROXY = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
    if PROXY:
        opts["proxy"] = PROXY

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
            raise RuntimeError("No output file produced")

        filename = os.path.basename(produced)
        return {
            "download_url": f"/files/{filename}",
            "filename": filename,
            "title": info.get("title"),
        }
    except yt_dlp.utils.DownloadError as e:
        print("yt-dlp DownloadError:", str(e))
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")
    except Exception as e:
        msg = str(e)
        print("Download error:", msg)
        if "No address associated with hostname" in msg:
            raise HTTPException(
                502,
                "DNS Error: runtime cannot access YouTube. Use HTTP_PROXY env or host on different provider."
            )
        raise HTTPException(status_code=500, detail=f"Download Error: {msg}")
