import os
import uuid
import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# FFmpeg Auto-Setup
import static_ffmpeg
static_ffmpeg.add_paths()

app = FastAPI()

# CORS
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

# Audio Only Format String
SPECIAL_AUDIO_FORMAT = "bestaudio[ext=m4a]/bestaudio"

@app.get("/")
def root():
    return {"status": "ok", "message": "Kaneki Downloader (Lite Version)"}

# ------------------------------------------------------------
# 1. SMART FORMATS
# ------------------------------------------------------------
@app.get("/formats")
def get_formats(url: str):
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    ydl_opts = {
        "quiet": True,
        "noplaylist": True,
        "skip_download": True,
        "nocheckcertificate": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        
        raw_formats = info.get('formats', [])
        available_heights = set()

        for f in raw_formats:
            if f.get('vcodec') != 'none' and f.get('height'):
                available_heights.add(f['height'])

        final_formats = []
        target_resolutions = [2160, 1440, 1080, 720, 480, 360]
        
        for res in target_resolutions:
            if res in available_heights:
                final_formats.append({
                    "format_id": f"v-{res}", 
                    "ext": "mp4",       
                    "vcodec": "h264",
                    "height": res,
                    "label": f"{res}p"
                })

        if not final_formats:
             final_formats.append({
                "format_id": "v-360",
                "ext": "mp4",
                "vcodec": "h264",
                "height": 360
            })

        return {"formats": final_formats}

    except Exception as e:
        print(f"Error analyzing: {e}")
        return {"formats": []}


# ------------------------------------------------------------
# 2. DOWNLOAD HANDLER (OPTIMIZED FOR SIZE)
# ------------------------------------------------------------
@app.get("/download")
def download(url: str, format_id: str):
    if not url or not format_id:
        raise HTTPException(status_code=400, detail="Missing parameters")

    try:
        uid = str(uuid.uuid4())[:8]
        out_tmpl = os.path.join(DOWNLOAD_DIR, f"kaneki_{uid}.%(ext)s")
        
        ydl_opts = {
            "outtmpl": out_tmpl,
            "quiet": True,
            "noplaylist": True,
            "nocheckcertificate": True,
            # Speed Fix: ရှုပ်ထွေးတဲ့ concurrent တွေဖြုတ်လိုက်ပါပြီ
            # ဒါက Server အသေးတွေမှာ ပိုငြိမ်ပြီး ပိုမြန်ပါတယ်
        }

        # --- VIDEO REQUEST ---
        if format_id.startswith("v-"):
            height = format_id.split("-")[1]
            # Video အတွက် Audio ကိုအရမ်းကြီးတာမယူဘဲ 128k အောက်ကိုပဲယူမယ် (မြန်အောင်လို့)
            ydl_opts["format"] = f"bestvideo[height={height}]+bestaudio[abr<=128]/best[height={height}]"
            ydl_opts["merge_output_format"] = "mp4"

        # --- AUDIO REQUEST (SUPER COMPRESSED) ---
        elif format_id == SPECIAL_AUDIO_FORMAT or "bestaudio" in format_id:
            # Source file ကိုကတည်းက အသေးဆုံးဖြစ်နိုင်တာကို အရင်ရှာဆွဲမယ်
            ydl_opts["format"] = "bestaudio[abr<=128]/bestaudio"
            
            # ပြီးမှ MP3 96kbps (Size အတော်သေး) သို့ ပြောင်းမယ်
            ydl_opts["postprocessors"] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '96', # 128 ကနေ 96 ပြောင်းလိုက်သည် (Size ပိုသေးရန်)
            }]
        
        else:
            ydl_opts["format"] = "best[ext=mp4]"


        # Execute Download
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # Video Extension Fix
            if format_id.startswith("v-") and filename.endswith(".mkv"):
                 pre, _ = os.path.splitext(filename)
                 if os.path.exists(pre + ".mp4"):
                     filename = pre + ".mp4"
            
            # Audio Extension Fix
            if "bestaudio" in format_id or format_id == SPECIAL_AUDIO_FORMAT:
                pre, _ = os.path.splitext(filename)
                if os.path.exists(pre + ".mp3"):
                    filename = pre + ".mp3"

        clean_filename = os.path.basename(filename)

        return {
            "download_url": f"/files/{clean_filename}",
            "filename": clean_filename
        }

    except Exception as e:
        print(f"DL Error: {e}")
        raise HTTPException(status_code=500, detail="Download Failed")
