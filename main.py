# main.py
# Kaneki Downloader - Complete Fix (No Cookies, Android Spoofing, Server-side Merge)

import os
import uuid
import glob
import urllib.parse as ul
import yt_dlp
from fastapi import FastAPI, HTTPException, BackgroundTasks, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

# --- FFmpeg Loading ---
# Server ပေါ်မှာ FFmpeg မရှိရင် static_ffmpeg ကို သုံးပါမယ်
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
    print("INFO: static_ffmpeg loaded successfully.")
except Exception:
    print("INFO: static_ffmpeg not found, relying on system ffmpeg.")

# ----------------- App setup -----------------
app = FastAPI(title="Kaneki Downloader V2.3 (Fixed)")

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

# ----------------- Configuration -----------------
AUDIO_ID = "mp3-best"

# Anti-Bot Settings (Cookies မလိုဘဲ YouTube ကိုကျော်မယ့်နည်းလမ်း)
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
        
        # --- Crucial Anti-Bot Settings ---
        "user_agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "extractor_args": {
            "youtube": {
                # Android Phone အနေနဲ့ ဟန်ဆောင်မည် (Cookies မလိုပါ)
                "player_client": ["android", "web"],
                "skip": ["dash", "hls"]
            }
        }
    }
    
    # Cookies ကို sengaja ပိတ်ထားပါတယ် (Cloud Server ပေါ်မှာ Cookies ကြောင့် Error တက်တတ်လို့ပါ)
    # if os.path.exists("cookies.txt"):
    #     opts["cookiefile"] = "cookies.txt"

    if extra:
        opts.update(extra)
    return opts

# ----------------- Utilities -----------------
def clean_url(url: str) -> str:
    """ URL တွေကို သန့်ရှင်းရေးလုပ်မယ့် Function """
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
    """ User ဆီ ဖိုင်ပို့ပြီးရင် Server ပေါ်ကဖိုင်ကို ပြန်ဖျက်မယ့် Function """
    try:
        if os.path.exists(path):
            os.remove(path)
            print(f"CLEANUP: Removed {path}")
        # ဆက်စပ်ဖိုင်များ (ဥပမာ .part) ကိုပါ ရှင်းလင်းခြင်း
        base_name = os.path.splitext(path)[0]
        for f in glob.glob(f"{base_name}*"):
            try:
                os.remove(f)
            except:
                pass
    except Exception as e:
        print(f"CLEANUP ERROR: {e}")

# ----------------- Health Checks (Fixes 405 Error) -----------------
@app.get("/")
def root():
    return {"status": "online", "message": "Kaneki Downloader is Running"}

@app.head("/")
def health_check():
    return Response(status_code=200)

# ----------------- Formats Endpoint -----------------
@app.get("/formats")
def get_formats(url: str):
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    
    url = clean_url(url)
    opts = ydl_base({"skip_download": True})
    
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
        raw = info.get("formats", [])
        # Video Resolutions (Only those with video codec)
        heights = sorted({int(f["height"]) for f in raw if f.get("height") and f.get("vcodec") != "none"}, reverse=True)
        
        simplified = []
        if heights:
            simplified.append({"format_id": "v-auto", "label": "Auto (Best Quality)", "ext": "mp4"})
            for h in heights:
                simplified.append({"format_id": f"v-{h}", "label": f"{h}p Quality", "ext": "mp4"})
        
        # Add MP3 Option
        simplified.append({"format_id": AUDIO_ID, "label": "Audio Only (MP3)", "ext": "mp3"})
        
        return {
            "title": info.get("title"),
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration_string"),
            "formats": simplified
        }
        
    except Exception as e:
        print(f"FORMAT ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ----------------- Download Endpoint -----------------
@app.get("/download")
def download_video(url: str, format_id: str, background_tasks: BackgroundTasks):
    if not url or not format_id:
        raise HTTPException(status_code=400, detail="Missing parameters")
    
    url = clean_url(url)
    unique_id = uuid.uuid4().hex
    output_template = os.path.join(DOWNLOAD_DIR, f"{unique_id}.%(ext)s")
    
    ydl_opts = {
        "outtmpl": output_template,
    }

    # 1. MP3 Logic
    if format_id == AUDIO_ID:
        ydl_opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        })
        target_ext = "mp3"

    # 2. Video Logic (Resolution Selection + Audio Merge)
    elif format_id.startswith("v-"):
        if format_id == "v-auto":
            ydl_opts.update({"format": "bestvideo+bestaudio/best"})
        else:
            try:
                height = int(format_id.split("-")[1])
                ydl_opts.update({"format": f"bestvideo[height<={height}]+bestaudio/best"})
            except:
                ydl_opts.update({"format": "bestvideo+bestaudio/best"})
        
        # Force merge to MP4 container
        ydl_opts.update({"merge_output_format": "mp4"})
        target_ext = "mp4"
    
    # 3. Fallback
    else:
        ydl_opts.update({"format": "best"})
        target_ext = "mp4"

    # Run Download
    final_opts = ydl_base(ydl_opts)
    try:
        print(f"Starting download for {url} ({format_id})...")
        with yt_dlp.YoutubeDL(final_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_title = info.get('title', 'video')
            
        # Clean filename for browser
        safe_filename = "".join([c for c in video_title if c.isalnum() or c in " .-_"]).strip()
        if not safe_filename: safe_filename = "download"
        download_filename = f"{safe_filename}.{target_ext}"
        
        # Locate the final file
        # (yt-dlp might change extension based on conversion)
        expected_file = os.path.join(DOWNLOAD_DIR, f"{unique_id}.{target_ext}")
        
        # If exact match not found, look for any file with that ID
        if not os.path.exists(expected_file):
            found = glob.glob(os.path.join(DOWNLOAD_DIR, f"{unique_id}*"))
            if found:
                expected_file = found[0] # Use the first match
            else:
                raise Exception("File not found after download.")

        # Schedule cleanup and return file
        background_tasks.add_task(cleanup_file, expected_file)
        
        return FileResponse(
            path=expected_file,
            filename=download_filename,
            media_type="application/octet-stream"
        )

    except Exception as e:
        print(f"DOWNLOAD FAILED: {str(e)}")
        # Cleanup partial files on error
        for f in glob.glob(os.path.join(DOWNLOAD_DIR, f"{unique_id}*")):
            try: os.remove(f)
            except: pass
            
        error_msg = str(e)
        if "Sign in" in error_msg:
            error_msg = "Server blocked by YouTube. Please try again later."
        raise HTTPException(status_code=500, detail=error_msg)
