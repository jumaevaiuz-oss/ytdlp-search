"""
Railway — ytdlp-search
Shared hosting (music_worker.php) dan kelgan so'rovni qabul qiladi:
  POST /download  → yt-dlp bilan MP3 yuklab, Telegram'ga yuboradi
  GET  /health    → server tirikligini tekshirish
"""

import os
import logging
import tempfile
import subprocess
import requests
from flask import Flask, request, jsonify

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────
BOT_TOKEN  = os.environ["BOT_TOKEN"]       # Railway → Variables
API_SECRET = os.environ["API_SECRET"]      # shared hosting bilan umumiy maxfiy kalit
PORT       = int(os.environ.get("PORT", 8080))

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
MAX_MB       = 48  # Telegram limiti 50MB, xavfsizlik uchun 48

app = Flask(__name__)


# ════════════════════════════════════════════════════════════
# ENDPOINTLAR
# ════════════════════════════════════════════════════════════

@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/download")
def download():
    """
    Shared hostingdan kelgan so'rov:
      secret      — API_SECRET bilan mosligini tekshiramiz
      chat_id     — Telegram chat ID
      youtube_url — https://www.youtube.com/watch?v=...
      title       — qo'shiq nomi
      artist      — artist nomi
    """
    secret = request.form.get("secret", "")
    if secret != API_SECRET:
        log.warning("Noto'g'ri secret: %s", secret)
        return jsonify({"error": "unauthorized"}), 403

    chat_id     = request.form.get("chat_id", "")
    youtube_url = request.form.get("youtube_url", "")
    title       = request.form.get("title", "Musiqa")
    artist      = request.form.get("artist", "")

    if not chat_id or not youtube_url:
        return jsonify({"error": "chat_id va youtube_url talab qilinadi"}), 400

    log.info("Yuklab olinmoqda: %s | %s", artist, title)

    # ── Kutish xabari ────────────────────────────────────────
    tg_send(chat_id, f"⏬ <b>{escape(artist)} – {escape(title)}</b>\n\nYuklab olinmoqda...")

    # ── Temp papka ───────────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmpdir:
        out_tmpl = os.path.join(tmpdir, "audio.%(ext)s")

        cmd = [
            "yt-dlp",
            "-x",
            "--audio-format",   "mp3",
            "--audio-quality",  "0",
            "-o",               out_tmpl,
            "--no-playlist",
            "--no-warnings",
            "--max-filesize",   f"{MAX_MB}m",
            "--socket-timeout", "30",
            youtube_url,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

        if result.returncode != 0:
            log.error("yt-dlp xato:\n%s", result.stderr)
            tg_send(chat_id, "❌ Yuklab olishda xatolik yuz berdi. Keyinroq urinib ko'ring.")
            return jsonify({"error": "yt-dlp failed"}), 500

        # ── Faylni topish ────────────────────────────────────
        mp3_path = os.path.join(tmpdir, "audio.mp3")
        if not os.path.exists(mp3_path):
            # Boshqa kengaytma bo'lishi mumkin
            files = [f for f in os.listdir(tmpdir) if f.startswith("audio")]
            if not files:
                tg_send(chat_id, "❌ Fayl yaratilmadi.")
                return jsonify({"error": "no output file"}), 500
            mp3_path = os.path.join(tmpdir, files[0])

        # ── Hajm tekshiruvi ──────────────────────────────────
        size_mb = os.path.getsize(mp3_path) / (1024 * 1024)
        if size_mb > MAX_MB:
            tg_send(chat_id, f"❌ Fayl hajmi {size_mb:.1f}MB — Telegram limiti {MAX_MB}MB.")
            return jsonify({"error": "file too large"}), 400

        # ── Telegram'ga yuborish ─────────────────────────────
        log.info("Yuborilmoqda: %.1fMB → chat %s", size_mb, chat_id)
        with open(mp3_path, "rb") as f:
            resp = requests.post(
                f"{TELEGRAM_API}/sendAudio",
                data={
                    "chat_id":   chat_id,
                    "title":     title,
                    "performer": artist,
                    "caption":   f"🎵 {artist} – {title}" if artist else f"🎵 {title}",
                },
                files={"audio": (f"{title}.mp3", f, "audio/mpeg")},
                timeout=120,
            )

        if resp.ok:
            log.info("Yuborildi ✓")
            return jsonify({"ok": True})
        else:
            log.error("sendAudio xato: %s", resp.text)
            tg_send(chat_id, "❌ Telegram'ga yuborishda xatolik.")
            return jsonify({"error": "telegram error"}), 500


# ════════════════════════════════════════════════════════════
# YORDAMCHI FUNKSIYALAR
# ════════════════════════════════════════════════════════════

def tg_send(chat_id: str, text: str):
    """Telegram'ga oddiy xabar yuboradi."""
    try:
        requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        log.warning("tg_send xato: %s", e)


def escape(text: str) -> str:
    """HTML maxsus belgilarini qochiradi."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


# ════════════════════════════════════════════════════════════
# START
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    log.info("Server port %s da ishlamoqda...", PORT)
    app.run(host="0.0.0.0", port=PORT)
