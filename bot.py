import os
import time
import asyncio
import sqlite3
import subprocess
from dotenv import load_dotenv
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
import yt_dlp

# Load secrets
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))

# ==========================================
# 1. DATABASE & ANTI-SPAM (SQLite)
# ==========================================
DB_FILE = "bot_users.db"
COOLDOWN_SECONDS = 30  # Anti-spam restriction


def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                last_request_time REAL,
                total_requests INTEGER DEFAULT 0
            )
        """)
        conn.commit()


def check_spam_and_update(user_id: int, username: str) -> bool:
    """Returns True if user is allowed, False if they are spamming."""
    current_time = time.time()
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT last_request_time FROM users WHERE user_id=?", (user_id,)
        )
        result = cursor.fetchone()

        if result:
            last_time = result[0]
            if current_time - last_time < COOLDOWN_SECONDS:
                return False  # Spam detected
            cursor.execute(
                """
                UPDATE users 
                SET last_request_time=?, total_requests=total_requests+1 
                WHERE user_id=?
            """,
                (current_time, user_id),
            )
        else:
            cursor.execute(
                """
                INSERT INTO users (user_id, username, last_request_time, total_requests) 
                VALUES (?, ?, ?, 1)
            """,
                (user_id, username, current_time),
            )
        conn.commit()
    return True


# ==========================================
# 2. MEDIA PROCESSING & DOWNLOADING
# ==========================================
async def compress_video(input_file: str, output_file: str):
    """Automatically compresses video to bypass Telegram's 50MB limit using FFmpeg."""
    # Target size 45MB to be safe (45 * 8192 kilobits)
    # This is a simplified 1-pass FFmpeg compression command.
    command = [
        "./ffmpeg",
        "-y",
        "-i",
        input_file,  # Changed "ffmpeg" to "./ffmpeg"
        "-fs",
        "45M",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-c:a",
        "aac",
        output_file,
    ]
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    await process.communicate()


def get_yt_dlp_options(format_type: str, filename: str) -> dict:
    """Configures yt-dlp based on format (Video or MP3) and handles cookies."""
    opts = {
        "outtmpl": filename,
        "noplaylist": True,
        "quiet": True,
        "ffmpeg_location": "./",  # ADD THIS LINE: Points yt-dlp to your local files
        "cookiefile": "cookies.txt",  # UNCOMMENT this line if you provide a cookies.txt file for auth
    }

    if format_type == "audio":
        opts.update(
            {
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
            }
        )
    else:
        # Try to get best video under 50MB, if none exists, get best and we compress later
        opts.update(
            {"format": "best[filesize<=50M]/bestvideo[filesize<=50M]+bestaudio/best"}
        )

    return opts


# ==========================================
# 3. TELEGRAM BOT HANDLERS
# ==========================================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    check_spam_and_update(user.id, user.username)

    welcome_msg = (
        "🇬🇧 **Welcome to the Video Downloader Bot!**\n"
        "Send me any social media link (YouTube, Instagram, TikTok, Twitter) to download it.\n\n"
        "🇦🇫 **به ربات دانلود ویدیو خوش آمدید!**\n"
        "هر لینک شبکه اجتماعی را برای دانلود بفرستید."
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")


async def link_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    user = update.effective_user

    if not check_spam_and_update(user.id, user.username):
        await update.message.reply_text(
            f"⏳ Please wait {COOLDOWN_SECONDS} seconds between requests. (لطفا کمی صبر کنید)"
        )
        return

    # Inline Keyboard for Format Selection
    keyboard = [
        [InlineKeyboardButton("🎬 Download Video (ویدیو)", callback_data=f"vid|{url}")],
        [InlineKeyboardButton("🎵 Extract Audio (صدا)", callback_data=f"aud|{url}")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Choose a format (فرمت را انتخاب کنید):", reply_markup=reply_markup
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    req_type, url = query.data.split("|", 1)
    chat_id = query.message.chat_id

    status_msg = await context.bot.send_message(
        chat_id=chat_id, text="⏳ Processing... (در حال پردازش...)"
    )

    file_id = f"{chat_id}_{int(time.time())}"
    raw_file = f"{file_id}.%(ext)s"
    final_file = f"{file_id}.mp4" if req_type == "vid" else f"{file_id}.mp3"

    opts = get_yt_dlp_options("audio" if req_type == "aud" else "video", raw_file)

    try:
        # 1. Download Media
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            downloaded_file = ydl.prepare_filename(info)

            # If audio, yt-dlp changes the extension to .mp3 automatically
            if req_type == "aud":
                downloaded_file = downloaded_file.rsplit(".", 1)[0] + ".mp3"

        # 2. Check Size & Compress if Video is > 48MB
        file_size_mb = os.path.getsize(downloaded_file) / (1024 * 1024)
        if req_type == "vid" and file_size_mb > 48.0:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg.message_id,
                text="🗜 File is large. Compressing... (در حال فشرده سازی...)",
            )
            compressed_file = f"compressed_{file_id}.mp4"
            await compress_video(downloaded_file, compressed_file)

            if os.path.exists(downloaded_file):
                os.remove(downloaded_file)
            downloaded_file = compressed_file

        # 3. Send Media
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_msg.message_id,
            text="📤 Uploading... (در حال آپلود...)",
        )

        with open(downloaded_file, "rb") as f:
            if req_type == "vid":
                await context.bot.send_video(
                    chat_id=chat_id, video=f, supports_streaming=True
                )
            else:
                await context.bot.send_audio(chat_id=chat_id, audio=f)

        # 4. Success Message
        await context.bot.send_message(
            chat_id=chat_id, text="✅ Download finished! (دانلود با موفقیت انجام شد!)"
        )

    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e).lower()
        if "sign in" in error_msg or "cookie" in error_msg:
            reply = (
                "⚠️ Authentication required. This video is age-restricted or private."
            )
        else:
            reply = "❌ Error downloading the media. The link might be invalid or unsupported."
        await context.bot.send_message(chat_id=chat_id, text=reply)

    finally:
        # Cleanup residual files
        for f in os.listdir("."):
            if file_id in f and os.path.exists(f):
                os.remove(f)
        await context.bot.delete_message(
            chat_id=chat_id, message_id=status_msg.message_id
        )


# ==========================================
# 4. WEB SERVICE SETUP (For Render.com)
# ==========================================
async def health_check(request):
    return web.Response(text="Bot is running smoothly 24/7!")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Web server listening on port {PORT}")


async def main():
    init_db()

    # Initialize Bot
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, link_received)
    )
    application.add_handler(CallbackQueryHandler(button_handler))

    # Start bot and web server simultaneously
    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    await start_web_server()

    # Keep application running
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    # nest_asyncio allows async code execution in environments with existing loops
    import nest_asyncio

    nest_asyncio.apply()
    asyncio.run(main())
