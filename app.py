from flask import Flask, request, jsonify, send_file
import yt_dlp
import os
import uuid
import threading

app = Flask(__name__)

API_KEY = os.environ.get("API_KEY", "mening_maxfiy_kalitim")

DOWNLOAD_DIR = "/tmp/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

MAX_SIZE_BYTES = 50 * 1024 * 1024  # 50MB


def delete_file_later(path, delay=60):
    def _delete():
        import time
        time.sleep(delay)
        if os.path.exists(path):
            os.remove(path)
    threading.Thread(target=_delete, daemon=True).start()


@app.route("/download", methods=["POST"])
def download():
    auth = request.headers.get("X-API-Key")
    if auth != API_KEY:
        return jsonify({"error": "Ruxsat yo'q"}), 401

    data = request.get_json()
    url = data.get("url")

    if not url:
        return jsonify({"error": "URL kiritilmagan"}), 400

    file_id = str(uuid.uuid4())
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

    # YouTube Shorts uchun
    if "youtube.com" in url or "youtu.be" in url:
        ydl_opts["extractor_args"] = {
            "youtube": {
                "player_client": ["android", "web"],
                "skip": ["translated_subs"],
            }
        }

    # Pinterest uchun
    if "pinterest.com" in url or "pin.it" in url:
        ydl_opts["format"] = "best"
        ydl_opts["http_headers"]["Referer"] = "https://www.pinterest.com/"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "video")

        downloaded_file = None
        for f in os.listdir(DOWNLOAD_DIR):
            if f.startswith(file_id):
                downloaded_file = os.path.join(DOWNLOAD_DIR, f)
                break

        if not downloaded_file:
            return jsonify({"error": "Fayl topilmadi"}), 500

        size = os.path.getsize(downloaded_file)
        if size > MAX_SIZE_BYTES:
            os.remove(downloaded_file)
            return jsonify({
                "error": "too_large",
                "message": f"Video hajmi {round(size/1024/1024, 1)}MB — 50MB dan katta",
            }), 413

        delete_file_later(downloaded_file, delay=60)
        return send_file(
            downloaded_file,
            as_attachment=True,
            download_name=f"{title}.mp4",
            mimetype="video/mp4"
        )

    except yt_dlp.utils.DownloadError as e:
        err = str(e)
        if "File is larger than max-filesize" in err:
            return jsonify({"error": "too_large", "message": "Video 50MB dan katta"}), 413
        return jsonify({"error": "Yuklab bo'lmadi", "detail": err}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/info", methods=["POST"])
def info():
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
