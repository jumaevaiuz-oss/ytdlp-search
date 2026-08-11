import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import yt_dlp

app = FastAPI()

class DownloadRequest(BaseModel):
    url: str = None
    search: str = None  # Musiqa nomi bo'yicha qidirish uchun

@app.post("/")
def process_audio(data: DownloadRequest):
    # Qaysi biri kelganini tekshiramiz (aniq havola yoki matnli qidiruv)
    target = data.url or data.search
    if not target:
        raise HTTPException(status_code=400, detail="URL yoki qidiruv matni kiritilmadi")

    # Agar matn bo'lsa, YouTube'dan qidirish prefiksini qo'shamiz
    if data.search:
        search_target = f"ytsearch1:{data.search}"
    else:
        search_target = data.url

    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_target, download=False)
            
            # Agar ytsearch ishlatilgan bo'lsa, natija ro'yxat (entries) bo'lib keladi
            if 'entries' in info:
                if not info['entries']:
                    raise HTTPException(status_code=404, detail="Musiqa topilmadi")
                info = info['entries'][0]

            audio_url = info.get('url')
            title = info.get('title', 'audio')

            if not audio_url:
                raise HTTPException(status_code=500, detail="Audio havolasini olib bo'lmadi")

            return {
                "status": "success",
                "title": title,
                "url": audio_url
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
  
