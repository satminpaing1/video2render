# main.py (fixed: added root health endpoint + existing features)
import os, uuid, time, glob, socket, requests, yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

app = FastAPI(title="Kaneki Downloader (fixed)")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
app.mount("/files", StaticFiles(directory=DOWNLOAD_DIR), name="files")

AUDIO_ID = "audio_mp3"

# ----- root health endpoint (prevents 404 on GET /) -----
@app.get("/", include_in_schema=False)
def root():
    return {"status": "ok", "message": "Kaneki Downloader running"}

# cookie handling (same as before)
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

# common headers to mimic browser
COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.youtube.com/"
}

def ytdl_common_opts(extra_opts=None):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 120,
        "force_ipv4": True,
        "extractor_args": {"youtube": {"player_client": ["android"]}},
        "http_headers": COMMON_HEADERS,
        "nocheckcertificate": True,
    }
    if COOKIE_PATH and os.path.exists(COOKIE_PATH):
        opts["cookiefile"] = COOKIE_PATH
    if extra_opts:
        opts.update(extra_opts)
    return opts

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
    for u in ["https://www.google.com", "https://www.youtube.com", "https://httpbin.org/ip"]:
        try:
            r = requests.get(u, timeout=6, headers=COMMON_HEADERS)
            http_results[u] = {"ok": True, "status": r.status_code}
        except Exception as e:
            http_results[u] = {"ok": False, "error": str(e)}
    return JSONResponse({"dns": dns_results, "http": http_results})

@app.get("/formats")
def formats(url: str):
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    extra = {"skip_download": True}
    opts = ytdl_common_opts(extra)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        raw = info.get("formats", []) or []
        formats_out = []
        seen_heights = set()
        for f in raw:
            if f.get("vcodec") != "none" and f.get("height"):
                try:
                    seen_heights.add(int(f["height"]))
                except:
                    pass
        formats_out.append({"format_id": "v-auto", "label": "Auto (best)", "ext": "mp4"})
        for h in [2160,1440,1080,720,480,360]:
            if h in seen_heights:
                formats_out.append({"format_id": f"v-{h}", "label": f"{h}p", "ext": "mp4"})
        audio_ids = []
        for f in raw:
            if f.get("acodec") != "none" and f.get("vcodec") == "none":
                audio_ids.append(f.get("format_id"))
        if audio_ids:
            formats_out.append({"format_id": AUDIO_ID, "label": "MP3 (128kbps)", "ext": "mp3"})
        return {"formats": formats_out, "raw_formats_sample": [{"id": x.get("format_id"), "ext": x.get("ext"), "height": x.get("height")} for x in raw][:30]}
    except Exception as e:
        msg = str(e)
        print("FORMAT ERROR:", msg)
        if "No address associated with hostname" in msg:
            return {"error": "DNS_ERROR", "detail": "Cannot reach YouTube from this runtime. Check /nettest."}
        if "Sign in to confirm you're not a bot" in msg or "use --cookies" in msg.lower():
            return {"error": "COOKIES_REQUIRED", "detail": "YouTube requires login cookies. Update YOUTUBE_COOKIES secret and redeploy."}
        return {"formats": []}

def find_output(prefix, attempts=20, wait=0.3):
    for _ in range(attempts):
        files = glob.glob(os.path.join(DOWNLOAD_DIR, prefix + "*"))
        if files:
            files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            return files[0]
        time.sleep(wait)
    return None

@app.get("/download")
def download(url: str, format_id: str):
    if not url or not format_id:
        raise HTTPException(400, "Missing parameters")
    uid = str(uuid.uuid4())[:8]
    prefix = f"kaneki_{uid}"
    outtmpl = os.path.join(DOWNLOAD_DIR, prefix + ".%(ext)s")
    opts = ytdl_common_opts({
        "outtmpl": outtmpl,
        "retries": 3,
        "continuedl": True,
        "postprocessors": []
    })
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
        opts["format"] = format_id
    try:
        print(f"Starting download uid={uid} url={url} format={format_id} opts_format={opts.get('format')}")
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        produced = find_output(prefix)
        if not produced:
            raise RuntimeError("Download finished but no output file found. Check logs.")
        filename = os.path.basename(produced)
        return {"download_url": f"/files/{filename}", "filename": filename, "title": info.get("title")}
    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        print("yt-dlp DownloadError:", msg)
        if "Sign in to confirm you're not a bot" in msg or "use --cookies" in msg.lower():
            raise HTTPException(502, "COOKIES_REQUIRED: YouTube requires login cookies. Update YOUTUBE_COOKIES secret and redeploy.")
        if "Requested format is not available" in msg:
            raise HTTPException(400, "FORMAT_NOT_AVAILABLE: Requested format isn't available for this video. Call /formats to pick another format.")
        raise HTTPException(status_code=500, detail=f"Download failed: {msg}")
    except Exception as e:
        msg = str(e)
        print("DOWNLOAD ERROR:", msg)
        if "No address associated with hostname" in msg:
            raise HTTPException(502, "DNS Error: Cannot reach YouTube from this runtime. Check /nettest or host elsewhere.")
        raise HTTPException(status_code=500, detail=f"Download Error: {msg}")
