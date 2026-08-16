from flask import Flask, request, jsonify, send_file
import yt_dlp
import os
import uuid
import threading
import urllib.request

app = Flask(__name__)

# API himoya kaliti - buni o'zgartiring!
API_KEY = os.environ.get("API_KEY", "mening_maxfiy_kalitim")

DOWNLOAD_DIR = "/tmp/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

MAX_SIZE_BYTES = 50 * 1024 * 1024  # 50MB


def delete_file_later(path, delay=60):
    """Faylni bir daqiqadan keyin o'chirish"""
    def _delete():
        import time
        time.sleep(delay)
        if os.path.exists(path):
            os.remove(path)
    threading.Thread(target=_delete, daemon=True).start()


@app.route("/download", methods=["POST"])
def download():
    # API kalitini tekshirish
    auth = request.headers.get("X-API-Key")
    if auth != API_KEY:
        return jsonify({"error": "Ruxsat yo'q"}), 401

    data = request.get_json()
    url = data.get("url")

    if not url:
        return jsonify({"error": "URL kiritilmagan"}), 400

    file_id = str(uuid.uuid4())
    output_path = os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s")

    is_pinterest = "pinterest.com" in url or "pin.it" in url

    ydl_opts = {
        "outtmpl": output_path,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "max_filesize": MAX_SIZE_BYTES,
    }

    # Pinterest uchun
    if is_pinterest:
        ydl_opts["format"] = "best/bestvideo+bestaudio/bestvideo/mp4"
        ydl_opts["http_headers"] = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Referer": "https://www.pinterest.com/",
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "media")

        # Yuklab olingan faylni topish
        downloaded_file = None
        for f in os.listdir(DOWNLOAD_DIR):
            if f.startswith(file_id):
                downloaded_file = os.path.join(DOWNLOAD_DIR, f)
                break

        # Pinterest rasm bo'lsa thumbnail yuklab olish
        if not downloaded_file and is_pinterest:
            thumbnail = info.get("thumbnail")
            if thumbnail:
                img_path = os.path.join(DOWNLOAD_DIR, f"{file_id}.jpg")
                req = urllib.request.Request(thumbnail, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    with open(img_path, "wb") as f:
                        f.write(resp.read())
                delete_file_later(img_path, delay=60)
                return send_file(img_path, as_attachment=True, download_name=f"{title}.jpg", mimetype="image/jpeg")
            return jsonify({"error": "Fayl topilmadi"}), 500

        if not downloaded_file:
            return jsonify({"error": "Fayl topilmadi"}), 500

        # Hajmini tekshirish
        size = os.path.getsize(downloaded_file)
        if size > MAX_SIZE_BYTES:
            os.remove(downloaded_file)
            return jsonify({
                "error": "too_large",
                "message": f"Fayl hajmi {round(size/1024/1024, 1)}MB — 50MB dan katta",
            }), 413

        # Fayl turini aniqlash (video yoki rasm)
        ext = downloaded_file.rsplit(".", 1)[-1].lower()
        if ext in ["jpg", "jpeg", "png", "webp"]:
            mimetype = f"image/{'jpeg' if ext == 'jpg' else ext}"
            download_name = f"{title}.{ext}"
        else:
            mimetype = "video/mp4"
            download_name = f"{title}.mp4"

        delete_file_later(downloaded_file, delay=60)
        return send_file(
            downloaded_file,
            as_attachment=True,
            download_name=download_name,
            mimetype=mimetype
        )

    except yt_dlp.utils.DownloadError as e:
        err = str(e)
        if "File is larger than max-filesize" in err:
            return jsonify({"error": "too_large", "message": "Fayl 50MB dan katta"}), 413
        # Pinterest rasm bo'lsa info dan thumbnail olish
        if is_pinterest:
            try:
                with yt_dlp.YoutubeDL({"quiet": True}) as ydl2:
                    info2 = ydl2.extract_info(url, download=False)
                thumbnail = info2.get("thumbnail")
                title2 = info2.get("title", "image")
                if thumbnail:
                    img_path = os.path.join(DOWNLOAD_DIR, f"{file_id}.jpg")
                    req = urllib.request.Request(thumbnail, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        with open(img_path, "wb") as f:
                            f.write(resp.read())
                    delete_file_later(img_path, delay=60)
                    return send_file(img_path, as_attachment=True, download_name=f"{title2}.jpg", mimetype="image/jpeg")
            except Exception:
                pass
        return jsonify({"error": "Yuklab bo'lmadi", "detail": err}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/info", methods=["POST"])
def info():
    """Video haqida ma'lumot olish (yuklab olmasdan)"""
    auth = request.headers.get("X-API-Key")
    if auth != API_KEY:
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


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
