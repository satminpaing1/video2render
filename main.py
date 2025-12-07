# main.py
# Kaneki Downloader - Force Fix (Cookies Disabled + Android Mode)

import os
import uuid
import glob
import urllib.parse as ul
import yt_dlp
from fastapi import FastAPI, HTTPException, BackgroundTasks, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

# --- FFmpeg Setup ---
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
    print("INFO: static_ffmpeg loaded.")
except Exception:
    print("INFO: System ffmpeg usage assumed.")

app = FastAPI(title="Kaneki Downloader Final Fix")

# CORS Setup
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

# ----------------- Important: Anti-Bot Configuration -----------------
def ydl_base(extra: dict = None):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "force_ipv4": True,
        "nocheckcertificate": True,
        "restrictfilenames": True,
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s"),
        
        # --- KEY FIX: Android Client Spoofing ---
        # Cookies မပါဘဲ Android Phone ဟန်ဆောင်မည့်နည်းလမ်း
        "user_agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"],
                "skip": ["dash", "hls"]
            }
        }
    }
    
    # ---------------------------------------------------------
    # CRITICAL CHANGE: Cookies Loading Disabled
    # Server ပေါ်မှာ Cookies ဖိုင်တွေ့ရင်တောင် မသုံးအောင် ပိတ်ထားလိုက်ပါပြီ
    # ---------------------------------------------------------
    # if os.path.exists("cookies.txt"):
    #     opts["cookiefile"] = "cookies.txt" 

    if extra:
        opts.update(extra)
    return opts

# ----------------- Helpers -----------------
def clean_url(url: str) -> str:
    if "youtube.com" in url or "youtu.be" in url:
        try:
            parsed = ul.urlparse(url)
            if parsed.netloc.endswith("youtu.be"):
                return f"https://www.youtube.com/watch?v={parsed.path.lstrip('/')}"
            qs = ul.parse_qs(parsed.query)
            if "v" in qs and qs["v"]:
                return f"https://www.youtube.com/watch?v={qs['v'][0]}"
        except:
            pass
    return url

def cleanup_file(path: str):
    try:
        if os.path.exists(path):
            os.remove(path)
        base = os.path.splitext(path)[0]
        for f in glob.glob(f"{base}*"):
            try: os.remove(f)
            except: pass
    except:
        pass

# ----------------- Endpoints -----------------

# Fix for 405 Method Not Allowed
@app.head("/")
def health_check_head():
    return Response(status_code=200)

@app.get("/")
def health_check():
    return {"status": "online", "message": "Kaneki Downloader Ready"}

@app.get("/formats")
def get_formats(url: str):
    if not url: raise HTTPException(400, "URL required")
    url = clean_url(url)
    
    # Skip download just to get JSON info
    opts = ydl_base({"skip_download": True})
    
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
        formats_raw = info.get("formats", [])
        heights = sorted({int(f["height"]) for f in formats_raw if f.get("height") and f.get("vcodec") != "none"}, reverse=True)
        
        simplified = [{"format_id": "v-auto", "label": "Auto (Best)", "ext": "mp4"}]
        for h in heights:
            simplified.append({"format_id": f"v-{h}", "label": f"{h}p", "ext": "mp4"})
        
        simplified.append({"format_id": "mp3-best", "label": "Audio Only (MP3)", "ext": "mp3"})
        
        return {
            "title": info.get("title"),
            "thumbnail": info.get("thumbnail"),
            "formats": simplified
        }
    except Exception as e:
        print(f"FORMAT ERROR: {e}")
        raise HTTPException(500, str(e))

@app.get("/download")
def download_media(url: str, format_id: str, background_tasks: BackgroundTasks):
    url = clean_url(url)
    uid = uuid.uuid4().hex
    # Prepare template
    cur_opts = {
        "outtmpl": os.path.join(DOWNLOAD_DIR, f"{uid}.%(ext)s")
    }
    
    target_ext = "mp4"
    
    if format_id == "mp3-best":
        cur_opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        })
        target_ext = "mp3"
    elif format_id.startswith("v-"):
        if format_id == "v-auto":
            cur_opts.update({"format": "bestvideo+bestaudio/best"})
        else:
            try:
                h = format_id.split("-")[1]
                cur_opts.update({"format": f"bestvideo[height<={h}]+bestaudio/best"})
            except:
                cur_opts.update({"format": "bestvideo+bestaudio/best"})
        cur_opts.update({"merge_output_format": "mp4"})
    else:
        cur_opts.update({"format": "best"})

    final_opts = ydl_base(cur_opts)
    
    try:
        with yt_dlp.YoutubeDL(final_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "video")
            
        safe_name = "".join([c for c in title if c.isalnum() or c in " .-_"]).strip() or "download"
        filename = f"{safe_name}.{target_ext}"
        
        # Find the file
        fpath = os.path.join(DOWNLOAD_DIR, f"{uid}.{target_ext}")
        if not os.path.exists(fpath):
            files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{uid}*"))
            if files: fpath = files[0]
            else: raise Exception("File missing after download")
            
        background_tasks.add_task(cleanup_file, fpath)
        
        return FileResponse(fpath, filename=filename, media_type="application/octet-stream")
        
    except Exception as e:
        print(f"DOWNLOAD ERROR: {e}")
        raise HTTPException(500, f"Server Error: {str(e)}")
