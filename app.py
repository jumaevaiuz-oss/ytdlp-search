from flask import Flask, request, jsonify, send_file, Response
import yt_dlp
import os
import uuid
import threading
import subprocess
import json

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


def check_auth(req):
    return req.headers.get("X-API-Key") == API_KEY


def get_video_meta(path):
    """ffprobe bilan video metadata olish"""
    try:
        result = subprocess.run([
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", path
        ], capture_output=True, text=True, timeout=30)
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                return {
                    "width": stream.get("width", 0),
                    "height": stream.get("height", 0),
                    "duration": int(float(stream.get("duration", 0))),
                }
    except:
        pass
    return {"width": 0, "height": 0, "duration": 0}


def make_thumbnail(video_path, thumb_path):
    """ffmpeg bilan video thumbnail yaratish"""
    try:
        subprocess.run([
            "ffmpeg", "-i", video_path,
            "-ss", "00:00:01",
            "-vframes", "1",
            "-vf", "scale=320:-1",
            "-y", thumb_path
        ], capture_output=True, timeout=30)
        return os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0
    except:
        return False


def convert_to_h264(input_path, output_path):
    """ffmpeg bilan H.264 ga konvert qilish"""
    try:
        result = subprocess.run([
            "ffmpeg", "-i", input_path,
            "-c:v", "libx264",
            "-c:a", "aac",
            "-movflags", "+faststart",
            "-preset", "fast",
            "-crf", "23",
            "-y", output_path
        ], capture_output=True, timeout=180)
        return os.path.exists(output_path) and os.path.getsize(output_path) > 10000
    except:
        return False


def gallery_dl_download(url, out_dir):
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


def send_video_response(f, title="video"):
    """Video faylni metadata bilan qaytarish"""
    size = os.path.getsize(f)
    if size > MAX_SIZE_BYTES:
        os.remove(f)
        return jsonify({"error": "too_large", "message": f"{round(size/1024/1024,1)}MB — 50MB dan katta"}), 413

    # H.264 ga konvert qilish
    converted = f.rsplit(".", 1)[0] + "_h264.mp4"
    if convert_to_h264(f, converted):
        os.remove(f)
        f = converted
    
    # Metadata olish
    meta = get_video_meta(f)

    # Thumbnail yaratish
    thumb_path = f.rsplit(".", 1)[0] + "_thumb.jpg"
    has_thumb = make_thumbnail(f, thumb_path)

    # Metadata ni header orqali yuborish
    headers = {
        "X-Video-Width": str(meta["width"]),
        "X-Video-Height": str(meta["height"]),
        "X-Video-Duration": str(meta["duration"]),
        "X-Has-Thumbnail": "1" if has_thumb else "0",
        "X-Thumb-Path": os.path.basename(thumb_path) if has_thumb else "",
        "Content-Disposition": f'attachment; filename="{title}.mp4"',
        "Content-Type": "video/mp4",
    }

    delete_file_later(f)
    if has_thumb:
        delete_file_later(thumb_path)

    return send_file(f, mimetype="video/mp4"), headers


@app.route("/download", methods=["POST"])
def download():
    if not check_auth(request):
        return jsonify({"error": "Ruxsat yo'q"}), 401

    data = request.get_json()
    url = data.get("url")
    if not url:
        return jsonify({"error": "URL kiritilmagan"}), 400

    file_id = str(uuid.uuid4())

    # Pinterest
    if "pinterest.com" in url or "pin.it" in url:
        out_dir = os.path.join(DOWNLOAD_DIR, file_id)
        try:
            files = gallery_dl_download(url, out_dir)
            if not files:
                return jsonify({"error": "Fayl topilmadi"}), 400
            f = files[0]
            ext = f.rsplit(".", 1)[-1].lower()
            if ext in ["mp4", "webm"]:
                resp, headers = send_video_response(f, "pinterest")
                delete_file_later(out_dir)
                return resp, 200, headers
            else:
                delete_file_later(out_dir)
                return send_file(f, mimetype="image/jpeg",
                    headers={"Content-Disposition": "attachment; filename=pinterest.jpg"})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    # Instagram
    if "instagram.com" in url or "instagr.am" in url:
        out_dir = os.path.join(DOWNLOAD_DIR, file_id)
        try:
            files = gallery_dl_download(url, out_dir)
            if files:
                f = files[0]
                ext = f.rsplit(".", 1)[-1].lower()
                if ext in ["mp4", "webm"]:
                    resp, headers = send_video_response(f, "instagram")
                    delete_file_later(out_dir)
                    return resp, 200, headers
                else:
                    delete_file_later(out_dir)
                    return send_file(f, mimetype="image/jpeg",
                        headers={"Content-Disposition": "attachment; filename=instagram.jpg"})
        except Exception:
            pass

    return _ytdlp_download(url, file_id)


@app.route("/download_multi", methods=["POST"])
def download_multi():
    if not check_auth(request):
        return jsonify({"error": "Ruxsat yo'q"}), 401

    data = request.get_json()
    url = data.get("url")
    if not url:
        return jsonify({"error": "URL kiritilmagan"}), 400

    file_id = str(uuid.uuid4())
    files_info = []

    # TikTok
    if "tiktok.com" in url or "vm.tiktok.com" in url:
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
            output_path = os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s")
            ydl_opts = {
                "outtmpl": output_path,
                "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "merge_output_format": "mp4",
                "quiet": True,
                "no_warnings": True,
                "max_filesize": MAX_SIZE_BYTES,
                "http_headers": {"User-Agent": "Mozilla/5.0"},
            }
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.extract_info(url, download=True)
                downloaded = sorted([
                    os.path.join(DOWNLOAD_DIR, f)
                    for f in os.listdir(DOWNLOAD_DIR)
                    if f.startswith(file_id) and not os.path.isdir(os.path.join(DOWNLOAD_DIR, f))
                ])
                for f in downloaded:
                    ext = f.rsplit(".", 1)[-1].lower()
                    ftype = "video" if ext in ["mp4", "webm"] else "photo"
                    files_info.append({"path": f, "type": ftype, "ext": ext})
            except Exception as e:
                return jsonify({"error": "TikTok yuklab bo'lmadi", "detail": str(e)}), 400

        if not files_info:
            return jsonify({"error": "TikTok fayl topilmadi"}), 400

    # Pinterest
    elif "pinterest.com" in url or "pin.it" in url:
        out_dir = os.path.join(DOWNLOAD_DIR, file_id)
        try:
            files = gallery_dl_download(url, out_dir)
            if not files:
                return jsonify({"error": "Fayl topilmadi"}), 400
            for f in files:
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

    # Video fayllar uchun metadata va thumbnail qo'shish
    result = []
    for item in files_info:
        fname = os.path.basename(item["path"])
        entry = {
            "file_url": f"/file/{fname}",
            "type": item["type"],
            "ext": item["ext"],
            "path": item["path"],
        }
        if item["type"] == "video":
            meta = get_video_meta(item["path"])
            entry["width"] = meta["width"]
            entry["height"] = meta["height"]
            entry["duration"] = meta["duration"]
            thumb_path = item["path"].rsplit(".", 1)[0] + "_thumb.jpg"
            if make_thumbnail(item["path"], thumb_path):
                entry["thumb_path"] = thumb_path
                entry["thumb_url"] = f"/file/{os.path.basename(thumb_path)}"
                delete_file_later(thumb_path)
        result.append(entry)

    return jsonify({"files": result, "count": len(result)})


@app.route("/file/<filename>")
def serve_file(filename):
    if not check_auth(request):
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
                "player_client": ["android", "web"],
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
        ext = f.rsplit(".", 1)[-1].lower()

        if ext in ["mp4", "webm", "mov", "avi", "mkv"]:
            resp, headers = send_video_response(f, title)
            return resp, 200, headers
        else:
            size = os.path.getsize(f)
            if size > MAX_SIZE_BYTES:
                os.remove(f)
                return jsonify({"error": "too_large", "message": f"{round(size/1024/1024,1)}MB — 50MB dan katta"}), 413
            mimetype = f"image/{'jpeg' if ext=='jpg' else ext}"
            delete_file_later(f)
            return send_file(f, mimetype=mimetype,
                headers={"Content-Disposition": f'attachment; filename="{title}.{ext}"'})

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


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
