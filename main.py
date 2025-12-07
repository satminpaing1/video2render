# main.py
# Kaneki Downloader - V4.0 (TV Embedded Mode)

import os
import uuid
import glob
import urllib.parse as ul
import yt_dlp
from fastapi import FastAPI, HTTPException, BackgroundTasks, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

# --- Version Info ---
VERSION = "V4.0 (TV Mode)"
print(f"------------------------------------------------")
print(f" KANEKI {VERSION} STARTING... ")
print(f"------------------------------------------------")

# --- Cleanup Old Cookies ---
# Server ပေါ်မှာ cookies.txt ကျန်နေရင် YouTube က Block တတ်လို့ အစကတည်းက ဖျက်ပါမယ်
if os.path.exists("cookies.txt"):
    try:
        os.remove("cookies.txt")
        print("INFO: Deleted old cookies.txt file.")
    except Exception as e:
        print(f"WARNING: Could not delete cookies.txt - {e}")

app = FastAPI(title=f"Kaneki Downloader {VERSION}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Frontend အားလုံးကို ခွင့်ပြုသည်
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ----------------- Configuration -----------------
def ydl_base(extra: dict = None):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "nocheckcertificate": True,
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s"),
        
        # --- NEW FIX: TV Embedded Mode ---
        # Smart TV ကနေ ကြည့်သလို ဟန်ဆောင်မယ့် နည်းလမ်း (IP Block ခံရသက်သာသည်)
        "extractor_args": {
            "youtube": {
                "player_client": ["tv_embedded", "web_embedded"],
                "skip": ["dash", "hls"]
            }
        },
        # User Agent ကိုမထည့်ဘဲ Default အတိုင်းထားတာက TV Mode မှာ ပိုအဆင်ပြေတတ်ပါတယ်
    }
    
    if extra:
        opts.update(extra)
    return opts

# ----------------- Utilities -----------------
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
@app.head("/")
def health_check_head():
    return Response(status_code=200)

@app.get("/")
def health_check():
    return {"status": "online", "version": VERSION}

@app.get("/formats")
def get_formats(url: str):
    if not url: raise HTTPException(400, "URL required")
    url = clean_url(url)
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
        # Return 500 but include error detail for debugging
        return JSONResponse(status_code=500, content={"detail": str(e), "error_type": "YouTube Block"})

@app.get("/download")
def download_media(url: str, format_id: str, background_tasks: BackgroundTasks):
    url = clean_url(url)
    uid = uuid.uuid4().hex
    
    cur_opts = {"outtmpl": os.path.join(DOWNLOAD_DIR, f"{uid}.%(ext)s")}
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
        
        # Locate file
        files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{uid}*"))
        if not files:
            raise Exception("File not found on server")
            
        final_path = files[0]
        final_filename = f"{safe_name}.{target_ext}"
        
        background_tasks.add_task(cleanup_file, final_path)
        return FileResponse(final_path, filename=final_filename, media_type="application/octet-stream")
        
    except Exception as e:
        print(f"DOWNLOAD ERROR: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})
