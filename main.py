# main.py
# Kaneki Downloader - V5.0 (Smart Multi-Client Switching)

import os
import uuid
import glob
import time
import urllib.parse as ul
import yt_dlp
from fastapi import FastAPI, HTTPException, BackgroundTasks, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

# --- Version Info ---
VERSION = "V5.0 (Smart Switch)"
print(f"------------------------------------------------")
print(f" KANEKI {VERSION} STARTING... ")
print(f"------------------------------------------------")

app = FastAPI(title=f"Kaneki Downloader {VERSION}")

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
COOKIE_FILE = os.path.join(BASE_DIR, "cookies.txt")

# ----------------- Configuration -----------------
# စမ်းသပ်မည့် Client များ (အစဉ်လိုက်)
CLIENTS_TO_TRY = [
    "android",          # Formats ဖတ်ရာတွင် အကောင်းဆုံး
    "web",              # Download လုပ်ရာတွင် တစ်ခါတစ်ရံ ပိုကောင်းသည်
    "mweb",             # Mobile Web
    "ios",              # iPhone
    "tv_embedded"       # နောက်ဆုံးမှ စမ်းမည်
]

def get_ydl_opts(client_type="android", extra: dict = None):
    """ Client အမျိုးအစားအလိုက် Setting ချပေးမည့် Function """
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 20,
        "nocheckcertificate": True,
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s"),
        
        # Client Spoofing logic
        "extractor_args": {
            "youtube": {
                "player_client": [client_type],
                "skip": ["dash", "hls"]
            }
        }
    }
    
    # Custom User Agent ကို ဖယ်လိုက်ပါပြီ (Conflict မဖြစ်အောင်)
    # Cookies ဖိုင်ရှိမှ ထည့်မည်
    if os.path.exists(COOKIE_FILE):
        opts["cookiefile"] = COOKIE_FILE

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
    
    last_error = ""
    
    # Smart Loop: Client တစ်ခုချင်းစီ အလှည့်ကျ စမ်းမည်
    for client in CLIENTS_TO_TRY:
        print(f"INFO: Trying to fetch formats with client: '{client}'...")
        opts = get_ydl_opts(client, {"skip_download": True})
        
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            
            # အဆင်ပြေရင် Loop ရပ်ပြီး Data ပြန်ပို့မည်
            print(f"SUCCESS: Formats fetched with '{client}'")
            
            formats_raw = info.get("formats", [])
            heights = sorted({int(f["height"]) for f in formats_raw if f.get("height") and f.get("vcodec") != "none"}, reverse=True)
            
            simplified = [{"format_id": "v-auto", "label": "Auto (Best)", "ext": "mp4"}]
            for h in heights:
                simplified.append({"format_id": f"v-{h}", "label": f"{h}p", "ext": "mp4"})
            simplified.append({"format_id": "mp3-best", "label": "Audio Only (MP3)", "ext": "mp3"})
            
            return {
                "title": info.get("title"),
                "thumbnail": info.get("thumbnail"),
                "formats": simplified,
                "used_client": client # Download လုပ်ရင် ပြန်သုံးဖို့ မှတ်သားထားမည်
            }
            
        except Exception as e:
            err_msg = str(e)
            print(f"FAIL: '{client}' failed. Error: {err_msg}")
            last_error = err_msg
            # နောက် Client တစ်ခု ဆက်စမ်းမည်
            continue

    # အကုန်စမ်းလို့မှ မရရင် Error ပြမည်
    print("ALL CLIENTS FAILED.")
    raise HTTPException(500, f"Failed to fetch info. YouTube blocked all attempts. Last error: {last_error}")

@app.get("/download")
def download_media(url: str, format_id: str, background_tasks: BackgroundTasks, used_client: str = "android"):
    url = clean_url(url)
    uid = uuid.uuid4().hex
    
    # Formats တုန်းက အလုပ်ဖြစ်ခဲ့တဲ့ Client ကို ဦးစားပေးသုံးမည်
    current_client = used_client if used_client in CLIENTS_TO_TRY else "android"
    
    cur_opts = {
        "outtmpl": os.path.join(DOWNLOAD_DIR, f"{uid}.%(ext)s")
    }
    
    # Format selection logic
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
        target_ext = "mp4"
    else:
        cur_opts.update({"format": "best"})
        target_ext = "mp4"

    # Download Attempt (Single try with the working client)
    final_opts = get_ydl_opts(current_client, cur_opts)
    
    try:
        print(f"STARTING DOWNLOAD with client '{current_client}'...")
        with yt_dlp.YoutubeDL(final_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "video")
            
        safe_name = "".join([c for c in title if c.isalnum() or c in " .-_"]).strip() or "download"
        
        files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{uid}*"))
        if not files:
            raise Exception("File not found on server")
            
        final_path = files[0]
        final_filename = f"{safe_name}.{target_ext}"
        
        background_tasks.add_task(cleanup_file, final_path)
        return FileResponse(final_path, filename=final_filename, media_type="application/octet-stream")
        
    except Exception as e:
        print(f"DOWNLOAD ERROR: {e}")
        # အကယ်၍ Download မှာမှ Error ထပ်တက်ရင် Fallback အနေနဲ့ Web Client နဲ့ ထပ်စမ်းကြည့်ခြင်း
        if current_client != "web":
            try:
                print("RETRYING download with 'web' client...")
                retry_opts = get_ydl_opts("web", cur_opts)
                with yt_dlp.YoutubeDL(retry_opts) as ydl:
                    ydl.extract_info(url, download=True)
                # (File finding logic repeated...)
                files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{uid}*"))
                if files:
                    background_tasks.add_task(cleanup_file, files[0])
                    return FileResponse(files[0], filename=f"{safe_name}.{target_ext}", media_type="application/octet-stream")
            except:
                pass
                
        raise HTTPException(500, f"Download Failed: {str(e)}")
