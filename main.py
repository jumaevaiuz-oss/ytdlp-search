import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import yt_dlp

app = FastAPI()

class DownloadRequest(BaseModel):
    url: str = None
    search: str = None

@app.post("/")
def process_audio(data: DownloadRequest):
    target = data.url or data.search
    if not target:
        raise HTTPException(status_code=400, detail="URL yoki qidiruv matni kiritilmadi")

    # Agar matn bo'lsa, uni qo'shiq qidirish uchun moslab prefiks beramiz
    if data.search:
        search_target = f"ytsearch1:{data.search} audio"
    else:
        search_target = data.url

    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_target, download=False)
            
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
        
