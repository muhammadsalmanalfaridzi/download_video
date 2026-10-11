import asyncio
import os
import secrets
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path

import imageio_ffmpeg
import uvicorn
import yt_dlp
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

OUT_DIR = Path(__file__).resolve().parent / "files"
OUT_DIR.mkdir(exist_ok=True)

# ffmpeg bawaan paket imageio-ffmpeg (pip install imageio-ffmpeg), tidak perlu install/PATH manual.
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
DEFAULT_FORMAT = "bv*+ba/b"

API_KEY = os.environ.get("API_KEY")  # wajib diisi; tanpa ini semua request ditolak (fail closed)
RETENTION_SECONDS = 3 * 24 * 3600


def cleanup_old_files():
    cutoff = time.time() - RETENTION_SECONDS
    for f in OUT_DIR.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    async def loop():
        while True:
            await asyncio.to_thread(cleanup_old_files)
            await asyncio.sleep(3600)

    task = asyncio.create_task(loop())
    yield
    task.cancel()


def require_api_key(x_api_key: str = Header(default="")):
    if not API_KEY:
        raise HTTPException(status_code=503, detail="API_KEY belum diset di server")
    if not secrets.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="API key salah")


app = FastAPI(title="Video Downloader API", description="Download video via yt-dlp", version="1.1.0", lifespan=lifespan)


class DownloadRequest(BaseModel):
    url: str = Field(description="URL video (YouTube, Zoom share, dll yang didukung yt-dlp)")
    format: str = Field(default=DEFAULT_FORMAT, description="Format selector yt-dlp")
    compress: bool = Field(default=True, description="Kompres hasil (H.264 CRF 28, maks 720p) agar kecil untuk WhatsApp")


def compress_video(src: Path) -> Path:
    dst = src.with_name(src.stem + " [compressed].mp4")
    subprocess.run(
        [FFMPEG, "-y", "-i", str(src), "-vf", "scale=-2:'min(720,ih)'", "-c:v", "libx264", "-crf", "28",
         "-preset", "veryfast", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(dst)],
        check=True, capture_output=True,
    )
    src.unlink()
    return dst


@app.post("/api/video/download", dependencies=[Depends(require_api_key)])
def download_video(req: DownloadRequest):
    opts = {
        "format": req.format,
        "outtmpl": str(OUT_DIR / "%(title).150B [%(id)s].%(ext)s"),
        "ffmpeg_location": FFMPEG,
        "merge_output_format": "mp4",
        "updatetime": False,  # mtime = waktu download (bukan tanggal upload), supaya cleanup 3 hari akurat
        "noplaylist": True,
        "quiet": True,
        "js_runtimes": {"node": {}},  # YouTube butuh JS runtime (deno default, node dipakai karena sudah terpasang)
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(req.url, download=True)
            path = Path(info["requested_downloads"][0]["filepath"])
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not path.exists():
        raise HTTPException(status_code=500, detail=f"File hasil download tidak ditemukan: {path.name}")
    if req.compress:
        try:
            path = compress_video(path)
        except subprocess.CalledProcessError as e:
            raise HTTPException(status_code=500, detail=f"Kompres gagal: {e.stderr.decode(errors='ignore')[-500:]}")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=8012, reload=True)
