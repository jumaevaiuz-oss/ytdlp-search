from flask import Flask, request, jsonify, send_file
import yt_dlp
import os
import uuid
import threading
import subprocess

app = Flask(__name__)

API_KEY = os.environ.get("API_KEY", "apikeyim")

DOWNLOAD_DIR = "/tmp/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

MAX_SIZE_BYTES = 50 * 1024 * 1024  # 50MB


def delete_file_later(path, delay=120):
    def _delete():
        import time, shutil
        time.sleep(delay)
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            elif os.path.exists(path):
                os.remove(path)
        except:
            pass
    threading.Thread(target=_delete, daemon=True).start()


def gallery_dl_download(url, out_dir):
    """gallery-dl bilan yuklab olish"""
    os.makedirs(out_dir, exist_ok=True)
    subprocess.run(
        ["gallery-dl", "-d", out_dir, "--no-download-archive", url],
        capture_output=True, text=True, timeout=60
    )
    files = []
    for root, dirs, filenames in os.walk(out_dir):
        for fname in sorted(filenames):
            fpath = os.path.join(root, fname)
            if fname.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".mp4", ".webm")):
                files.append(fpath)
    return files


def check_auth(req):
    return req.headers.get("X-API-Key") == API_KEY


@app.route("/download", methods=["POST"])
def download():
    """Bitta fayl qaytaradi"""
    if not check_auth(request):
        return jsonify({"error": "Ruxsat yo'q"}), 401

    data = request.get_json()
    url = data.get("url")
    if not url:
        return jsonify({"error": "URL kiritilmagan"}), 400

    file_id = str(uuid.uuid4())

    # Pinterest — gallery-dl
    if "pinterest.com" in url or "pin.it" in url:
        out_dir = os.path.join(DOWNLOAD_DIR, file_id)
        try:
            files = gallery_dl_download(url, out_dir)
            if not files:
                return jsonify({"error": "Fayl topilmadi"}), 400
            f = files[0]
            ext = f.rsplit(".", 1)[-1].lower()
            mimetype = "video/mp4" if ext in ["mp4", "webm"] else "image/jpeg"
            delete_file_later(out_dir)
            return send_file(f, as_attachment=True, download_name=f"pinterest.{ext}", mimetype=mimetype)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    # Instagram — gallery-dl
    if "instagram.com" in url or "instagr.am" in url:
        out_dir = os.path.join(DOWNLOAD_DIR, file_id)
        try:
            files = gallery_dl_download(url, out_dir)
            if files:
                f = files[0]
                ext = f.rsplit(".", 1)[-1].lower()
                mimetype = "video/mp4" if ext in ["mp4", "webm"] else "image/jpeg"
                delete_file_later(out_dir)
                return send_file(f, as_attachment=True, download_name=f"instagram.{ext}", mimetype=mimetype)
        except Exception:
            pass

    # yt-dlp
    return _ytdlp_download(url, file_id)


@app.route("/download_multi", methods=["POST"])
def download_multi():
    """Bir nechta fayl URL ro'yxatini qaytaradi (media group uchun)"""
    if not check_auth(request):
        return jsonify({"error": "Ruxsat yo'q"}), 401

    data = request.get_json()
    url = data.get("url")
    if not url:
        return jsonify({"error": "URL kiritilmagan"}), 400

    file_id = str(uuid.uuid4())
    files_info = []

    # TikTok slideshow
    if "tiktok.com" in url or "vm.tiktok.com" in url:
        output_path = os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s")
        ydl_opts = {
            "outtmpl": output_path,
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
            "max_filesize": MAX_SIZE_BYTES,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
            },
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)
            downloaded = sorted([
                os.path.join(DOWNLOAD_DIR, f)
                for f in os.listdir(DOWNLOAD_DIR)
                if f.startswith(file_id) and not os.path.isdir(os.path.join(DOWNLOAD_DIR, f))
            ])
            if not downloaded:
                return jsonify({"error": "TikTok fayl topilmadi"}), 400
            for f in downloaded:
                ext = f.rsplit(".", 1)[-1].lower()
                ftype = "video" if ext in ["mp4", "webm"] else "photo"
                files_info.append({"path": f, "type": ftype, "ext": ext})
        except Exception as e:
            return jsonify({"error": "TikTok yuklab bo'lmadi", "detail": str(e)}), 400

    # Pinterest
    elif "pinterest.com" in url or "pin.it" in url:
        out_dir = os.path.join(DOWNLOAD_DIR, file_id)
        try:
            files = gallery_dl_download(url, out_dir)
            if not files:
                return jsonify({"error": "Fayl topilmadi"}), 400
            for i, f in enumerate(files):
                ext = f.rsplit(".", 1)[-1].lower()
                ftype = "video" if ext in ["mp4", "webm"] else "photo"
                files_info.append({"path": f, "type": ftype, "ext": ext})
            delete_file_later(out_dir)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    # Instagram
    elif "instagram.com" in url or "instagr.am" in url:
        out_dir = os.path.join(DOWNLOAD_DIR, file_id)
        try:
            files = gallery_dl_download(url, out_dir)
            if files:
                for f in files:
                    ext = f.rsplit(".", 1)[-1].lower()
                    ftype = "video" if ext in ["mp4", "webm"] else "photo"
                    files_info.append({"path": f, "type": ftype, "ext": ext})
                delete_file_later(out_dir)
        except Exception:
            pass

        if not files_info:
            return _ytdlp_download(url, file_id)

    else:
        return _ytdlp_download(url, file_id)

    if not files_info:
        return jsonify({"error": "Fayl topilmadi"}), 400

    result = []
    for item in files_info:
        fname = os.path.basename(item["path"])
        result.append({
            "file_url": f"/file/{fname}",
            "type": item["type"],
            "ext": item["ext"],
            "path": item["path"]
        })

    return jsonify({"files": result, "count": len(result)})


@app.route("/file/<filename>")
def serve_file(filename):
    """Faylni yuborish"""
    auth = request.headers.get("X-API-Key")
    if auth != API_KEY:
        return jsonify({"error": "Ruxsat yo'q"}), 401

    for root, dirs, filenames in os.walk(DOWNLOAD_DIR):
        if filename in filenames:
            fpath = os.path.join(root, filename)
            ext = filename.rsplit(".", 1)[-1].lower()
            mimetype = "video/mp4" if ext in ["mp4", "webm"] else "image/jpeg"
            return send_file(fpath, mimetype=mimetype)

    return jsonify({"error": "Fayl topilmadi"}), 404


def _ytdlp_download(url, file_id):
    output_path = os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s")

    ydl_opts = {
        "outtmpl": output_path,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "max_filesize": MAX_SIZE_BYTES,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        },
        "nocheckcertificate": True,
        "geo_bypass": True,
    }

    if "youtube.com" in url or "youtu.be" in url:
        ydl_opts["extractor_args"] = {
            "youtube": {
                "player_client": ["tv_embedded"],
                "skip": ["translated_subs"],
            }
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "media")

        downloaded = [
            os.path.join(DOWNLOAD_DIR, f)
            for f in os.listdir(DOWNLOAD_DIR)
            if f.startswith(file_id) and not os.path.isdir(os.path.join(DOWNLOAD_DIR, f))
        ]

        if not downloaded:
            return jsonify({"error": "Fayl topilmadi"}), 500

        f = downloaded[0]
        size = os.path.getsize(f)
        if size > MAX_SIZE_BYTES:
            os.remove(f)
            return jsonify({"error": "too_large", "message": f"{round(size/1024/1024,1)}MB — 50MB dan katta"}), 413

        ext = f.rsplit(".", 1)[-1].lower()
        mimetype = "video/mp4" if ext in ["mp4", "webm"] else f"image/{'jpeg' if ext=='jpg' else ext}"
        delete_file_later(f)
        return send_file(f, as_attachment=True, download_name=f"{title}.{ext}", mimetype=mimetype)

    except yt_dlp.utils.DownloadError as e:
        err = str(e)
        if "File is larger than max-filesize" in err:
            return jsonify({"error": "too_large", "message": "50MB dan katta"}), 413
        return jsonify({"error": "Yuklab bo'lmadi", "detail": err}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/info", methods=["POST"])
def info():
    if not check_auth(request):
        return jsonify({"error": "Ruxsat yo'q"}), 401

    data = request.get_json()
    url = data.get("url")
    if not url:
        return jsonify({"error": "URL kiritilmagan"}), 400

    try:
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            return jsonify({
                "title": info.get("title"),
                "duration": info.get("duration"),
                "filesize": info.get("filesize") or info.get("filesize_approx"),
                "thumbnail": info.get("thumbnail"),
                "uploader": info.get("uploader"),
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# =============================================
# MUSIQA ENDPOINTS
# =============================================

@app.route("/music/search", methods=["POST"])
def music_search():
    """YouTube'dan musiqa qidiradi, 10 ta natija qaytaradi"""
    if not check_auth(request):
        return jsonify({"error": "Ruxsat yo'q"}), 401

    data = request.get_json()
    query = data.get("query")
    if not query:
        return jsonify({"error": "Query kiritilmagan"}), 400

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "default_search": "ytsearch10",
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            results = ydl.extract_info(f"ytsearch10:{query}", download=False)

        tracks = []
        for entry in results.get("entries", []):
            if not entry:
                continue
            duration = entry.get("duration")
            if duration:
                minutes = int(duration) // 60
                seconds = int(duration) % 60
                duration_str = f"{minutes}:{seconds:02d}"
            else:
                duration_str = "?"

            tracks.append({
                "id": entry.get("id"),
                "title": entry.get("title"),
                "url": entry.get("url") or f"https://www.youtube.com/watch?v={entry.get('id')}",
                "duration": duration_str,
                "uploader": entry.get("uploader") or entry.get("channel", ""),
            })

        return jsonify({"tracks": tracks, "count": len(tracks)})

    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/music/download", methods=["POST"])
def music_download():
    """YouTube video ID yoki URL'dan MP3 yuklab beradi"""
    if not check_auth(request):
        return jsonify({"error": "Ruxsat yo'q"}), 401

    data = request.get_json()
    url = data.get("url")
    if not url:
        return jsonify({"error": "URL kiritilmagan"}), 400

    # Agar faqat video ID bo'lsa, URL'ga aylantirish
    if not url.startswith("http"):
        url = f"https://www.youtube.com/watch?v={url}"

    file_id = str(uuid.uuid4())
    output_path = os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s")

    ydl_opts = {
        "outtmpl": output_path,
        "format": "bestaudio/best",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "extractor_args": {
            "youtube": {
                "player_client": ["tv_embedded"],
            }
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "music")

        # MP3 faylini topish
        downloaded = [
            os.path.join(DOWNLOAD_DIR, f)
            for f in os.listdir(DOWNLOAD_DIR)
            if f.startswith(file_id)
        ]

        if not downloaded:
            return jsonify({"error": "Fayl topilmadi"}), 500

        f = downloaded[0]
        size = os.path.getsize(f)

        if size > MAX_SIZE_BYTES:
            os.remove(f)
            return jsonify({"error": "too_large", "message": f"{round(size/1024/1024,1)}MB — 50MB dan katta"}), 413

        delete_file_later(f)
        return send_file(
            f,
            as_attachment=True,
            download_name=f"{title}.mp3",
            mimetype="audio/mpeg"
        )

    except yt_dlp.utils.DownloadError as e:
        return jsonify({"error": "Yuklab bo'lmadi", "detail": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
