import os
import logging
import tempfile
import json
import subprocess
from pathlib import Path

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    InlineQueryHandler,
    ContextTypes,
    filters,
)

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# --- Config (Railway environment variables dan o'qiladi) ---
BOT_TOKEN = os.environ["BOT_TOKEN"]
MAX_FILE_SIZE_MB = 50  # Telegram limiti

# ─────────────────────────────────────────────
# YT-DLP YORDAMCHI FUNKSIYALAR
# ─────────────────────────────────────────────

def run_ytdlp(args: list[str]) -> tuple[str, str, int]:
    """yt-dlp ni subprocess orqali ishlatadi."""
    result = subprocess.run(
        ["yt-dlp"] + args,
        capture_output=True,
        text=True,
    )
    return result.stdout, result.stderr, result.returncode


def search_music(query: str, limit: int = 6) -> list[dict]:
    """YouTube'dan musiqa qidiradi."""
    stdout, stderr, code = run_ytdlp([
        f"ytsearch{limit}:{query}",
        "--dump-json",
        "--flat-playlist",
        "--no-playlist",
        "--no-warnings",
    ])
    results = []
    for line in stdout.strip().split("\n"):
        if not line:
            continue
        try:
            data = json.loads(line)
            duration = data.get("duration")
            if duration:
                mins, secs = divmod(int(duration), 60)
                duration_str = f"{mins}:{secs:02d}"
            else:
                duration_str = "?"
            results.append({
                "id": data.get("id", ""),
                "title": data.get("title", "Noma'lum"),
                "duration": duration_str,
                "uploader": data.get("uploader", ""),
                "url": f"https://youtube.com/watch?v={data.get('id', '')}",
            })
        except json.JSONDecodeError:
            continue
    return results


def get_video_info(url: str) -> dict | None:
    """Video haqida ma'lumot oladi."""
    stdout, _, code = run_ytdlp([
        url,
        "--dump-json",
        "--no-playlist",
        "--no-warnings",
    ])
    if not stdout.strip():
        return None
    try:
        return json.loads(stdout.strip().split("\n")[0])
    except json.JSONDecodeError:
        return None


def download_audio(url: str, output_path: str) -> bool:
    """Musiqani MP3 formatda yuklab oladi."""
    _, _, code = run_ytdlp([
        url,
        "-x",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "-o", output_path,
        "--no-playlist",
        "--no-warnings",
        "--max-filesize", f"{MAX_FILE_SIZE_MB}m",
    ])
    return code == 0


def download_video(url: str, output_path: str) -> bool:
    """Videoni MP4 formatda yuklab oladi."""
    _, _, code = run_ytdlp([
        url,
        "-f", "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4][height<=720]/best",
        "--merge-output-format", "mp4",
        "-o", output_path,
        "--no-playlist",
        "--no-warnings",
        "--max-filesize", f"{MAX_FILE_SIZE_MB}m",
    ])
    return code == 0


# ─────────────────────────────────────────────
# COMMAND HANDLER'LAR
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Salom! Men video va musiqa yuklab beruvchi botman.\n\n"
        "📹 *Video yuklab olish:*\n"
        "YouTube, Instagram, TikTok va boshqa saytlardan link yuboring.\n\n"
        "🎵 *Musiqa izlash:*\n"
        "/music <qo'shiq nomi> — musiqa qidirish\n\n"
        "💡 *Misol:*\n"
        "/music Shaxriyar Abdullayev\n"
        "yoki shunchaki video linkini yuboring."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🆘 *Yordam*\n\n"
        "• Video link yuboring → bot yuklab beradi\n"
        "• /music <nom> → musiqa qidiradi\n"
        "• Inline rejim: @botusername <qo'shiq> yozib guruhda ham izlash mumkin\n\n"
        "⚠️ Fayl hajmi 50MB dan oshmasligi kerak."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ─────────────────────────────────────────────
# MUSIQA IZLASH
# ─────────────────────────────────────────────

async def music_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "🎵 Qo'shiq nomini kiriting:\n`/music Shaxriyar Abdullayev`",
            parse_mode="Markdown",
        )
        return

    query = " ".join(context.args)
    msg = await update.message.reply_text(f"🔍 *{query}* qidirilmoqda...", parse_mode="Markdown")

    results = search_music(query)
    if not results:
        await msg.edit_text("❌ Hech narsa topilmadi.")
        return

    text = f"🎵 *\"{query}\"* bo'yicha natijalar:\n\n"
    keyboard = []
    for i, r in enumerate(results, 1):
        text += f"{i}. {r['title']} — `{r['duration']}`\n"
        keyboard.append([
            InlineKeyboardButton(
                f"🎵 {i}. {r['title'][:35]}...",
                callback_data=f"audio|{r['id']}|{r['title'][:30]}",
            )
        ])

    await msg.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


# ─────────────────────────────────────────────
# VIDEO LINK ORQALI YUKLAB OLISH
# ─────────────────────────────────────────────

SUPPORTED_DOMAINS = [
    "youtube.com", "youtu.be",
    "instagram.com",
    "tiktok.com",
    "twitter.com", "x.com",
    "facebook.com",
    "vk.com",
    "ok.ru",
    "dailymotion.com",
    "twitch.tv",
]


def is_video_url(text: str) -> bool:
    text = text.lower()
    return any(domain in text for domain in SUPPORTED_DOMAINS)


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()

    if not is_video_url(url):
        return  # Boshqa xabarlarni e'tiborsiz qoldiradi

    msg = await update.message.reply_text("⏳ Video ma'lumotlari olinmoqda...")

    info = get_video_info(url)
    if not info:
        await msg.edit_text("❌ Bu linkdan video topilmadi.")
        return

    title = info.get("title", "Video")[:50]
    duration = info.get("duration", 0)
    mins, secs = divmod(int(duration or 0), 60)

    text = (
        f"📹 *{title}*\n"
        f"⏱ Davomiyligi: {mins}:{secs:02d}\n\n"
        f"Nima yuklab olmoqchisiz?"
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎵 Faqat audio (MP3)", callback_data=f"audio_url|{url}|{title}"),
            InlineKeyboardButton("📹 Video (MP4)", callback_data=f"video_url|{url}|{title}"),
        ]
    ])
    await msg.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)


# ─────────────────────────────────────────────
# CALLBACK HANDLER (Tugma bosilganda)
# ─────────────────────────────────────────────

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # --- Musiqa ID orqali yuklab olish ---
    if data.startswith("audio|"):
        _, video_id, title = data.split("|", 2)
        url = f"https://youtube.com/watch?v={video_id}"
        await _send_audio(query, url, title)

    # --- URL orqali audio ---
    elif data.startswith("audio_url|"):
        _, url, title = data.split("|", 2)
        await _send_audio(query, url, title)

    # --- URL orqali video ---
    elif data.startswith("video_url|"):
        _, url, title = data.split("|", 2)
        await _send_video(query, url, title)


async def _send_audio(query, url: str, title: str):
    await query.edit_message_text(f"⏬ *{title}* yuklab olinmoqda...", parse_mode="Markdown")
    with tempfile.TemporaryDirectory() as tmpdir:
        output = os.path.join(tmpdir, "audio.mp3")
        success = download_audio(url, output)

        if not success or not os.path.exists(output):
            await query.edit_message_text("❌ Yuklab olishda xatolik yuz berdi.")
            return

        file_size = os.path.getsize(output) / (1024 * 1024)
        if file_size > MAX_FILE_SIZE_MB:
            await query.edit_message_text(f"❌ Fayl hajmi {file_size:.1f}MB — Telegram limiti 50MB.")
            return

        await query.edit_message_text(f"📤 *{title}* yuborilmoqda...", parse_mode="Markdown")
        with open(output, "rb") as f:
            await query.message.reply_audio(audio=f, title=title, performer="yt-dlp bot")
        await query.delete_message()


async def _send_video(query, url: str, title: str):
    await query.edit_message_text(f"⏬ *{title}* yuklab olinmoqda...", parse_mode="Markdown")
    with tempfile.TemporaryDirectory() as tmpdir:
        output = os.path.join(tmpdir, "video.mp4")
        success = download_video(url, output)

        if not success or not os.path.exists(output):
            await query.edit_message_text("❌ Yuklab olishda xatolik yuz berdi.")
            return

        file_size = os.path.getsize(output) / (1024 * 1024)
        if file_size > MAX_FILE_SIZE_MB:
            await query.edit_message_text(f"❌ Fayl hajmi {file_size:.1f}MB — Telegram limiti 50MB.")
            return

        await query.edit_message_text(f"📤 *{title}* yuborilmoqda...", parse_mode="Markdown")
        with open(output, "rb") as f:
            await query.message.reply_video(video=f, caption=f"📹 {title}")
        await query.delete_message()


# ─────────────────────────────────────────────
# INLINE REJIM (Guruhda @bot query)
# ─────────────────────────────────────────────

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_text = update.inline_query.query.strip()
    if len(query_text) < 2:
        return

    results_data = search_music(query_text, limit=5)
    results = []
    for r in results_data:
        results.append(
            InlineQueryResultArticle(
                id=r["id"],
                title=r["title"],
                description=f"⏱ {r['duration']} | {r['uploader']}",
                input_message_content=InputTextMessageContent(
                    f"🎵 {r['title']}\n🔗 {r['url']}"
                ),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "🎵 Yuklab olish",
                        callback_data=f"audio|{r['id']}|{r['title'][:30]}",
                    )
                ]]),
            )
        )
    await update.inline_query.answer(results, cache_time=30)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("music", music_search))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))

    logger.info("Bot ishga tushdi...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
