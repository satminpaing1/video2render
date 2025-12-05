from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import yt_dlp
import os
import uuid

app = FastAPI()

# Allow all CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Serve files
app.mount("/files", StaticFiles(directory=DOWNLOAD_DIR), name="files")

@app.get("/")
def root():
    return {"status": "ok", "message": "ThuYaAungZaw Downloader API (FFMPEG Enabled)"}


# ------------------------------------------------------------
#  FORMATS (only valid video/audio formats)
# ------------------------------------------------------------
@app.get("/formats")
def get_formats(url: str):
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "nocheckcertificate": True,
        "noplaylist": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        extractor = (info.get("extractor") or "").lower()
        fmts = []

        for f in info.get("formats", []):
            vcodec = (f.get("vcodec") or "").lower()
            acodec = (f.get("acodec") or "").lower()
            ext = (f.get("ext") or "").lower()
            height = f.get("height") or 0
            fps = f.get("fps")

            # ignore audio-only
            if vcodec == "none":
                continue

            # ignore video-only ONLY if it's not YouTube (YT needs merging)
            if "youtube" not in extractor:
                if acodec == "none":
                    continue

            # only mp4 allowed (we will merge to mp4)
            if ext != "mp4":
                continue

            # create label
            label = ""
            if height:
                label = f"{height}p"
            if fps:
                label += f" {fps}fps"

            if not label:
                label = f.get("format_note") or f.get("format_id")

            fmts.append({
                "format_id": f.get("format_id"),
                "label": label,
                "height": height,
            })

        # sort highest → lowest
        fmts.sort(key=lambda x: x["height"], reverse=True)

        # remove height when returning
        for f in fmts:
            f.pop("height", None)

        return {"formats": fmts}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------
#  DOWNLOAD (FFMPEG MERGE ENABLED)
# ------------------------------------------------------------
def download_with_ytdlp(url: str, format_id: str) -> str:
    """
    This version merges video+audio into playable MP4.
    Required: Railway Pro (FFmpeg installed)
    """

    unique_name = str(uuid.uuid4())
    out_path = os.path.join(DOWNLOAD_DIR, unique_name + ".mp4")

    ydl_opts = {
        "format": format_id + "+bestaudio/best",  # force merge
        "outtmpl": out_path,
        "merge_output_format": "mp4",             # ensure playable MP4
        "quiet": True,
        "noplaylist": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    return os.path.basename(out_path)


@app.get("/download")
def download(url: str, format_id: str):
    if not url or not format_id:
        raise HTTPException(status_code=400, detail="Missing parameters")

    try:
        filename = download_with_ytdlp(url, format_id)

        return {
            "download_url": f"/file/{filename}",
            "filename": filename,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/file/{filename}")
def get_file(filename: str):
    filepath = os.path.join(DOWNLOAD_DIR, filename)

    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(filepath, media_type="video/mp4", filename=filename)