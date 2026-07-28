import asyncio
import os
import re
import sqlite3
import stat
import time
import uuid

import cronitor
import yt_dlp
from aiohttp import web
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Load secrets
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))
CRONITOR_API_KEY = os.getenv("CRONITOR_API_KEY")

# ==========================================
# 1. DATABASE (Anti-Spam per User)
# ==========================================
DB_FILE = "bot_users.db"
COOLDOWN_SECONDS = 30


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
    """Tracks users across all groups. Ensures individual spammers are blocked."""
    current_time = time.time()
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT last_request_time FROM users WHERE user_id=?", (user_id,)
        )
        result = cursor.fetchone()

        if result:
            if current_time - result[0] < COOLDOWN_SECONDS:
                return False
            cursor.execute(
                """
                UPDATE users SET last_request_time=?, total_requests=total_requests+1 
                WHERE user_id=?
            """,
                (current_time, user_id),
            )
        else:
            # FIXED: Added the 4th question mark (?) to match the 4 values supplied below
            cursor.execute(
                """
                INSERT INTO users (user_id, username, last_request_time, total_requests) 
                VALUES (?, ?, ?, ?)
            """,
                (user_id, username, current_time, 1),
            )
        conn.commit()
    return True


# ==========================================
# 2. MEDIA PROCESSING (Static FFmpeg)
# ==========================================
async def compress_video(input_file: str, output_file: str):
    """Runs local static FFmpeg as a non-blocking background task."""
    command = [
        "./ffmpeg",
        "-y",
        "-i",
        input_file,
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
    opts = {
        "outtmpl": filename,
        "noplaylist": True,
        "quiet": True,
        "ffmpeg_location": "./",  # Works on Render (Linux). Will fail on Windows locally unless you add ffmpeg.exe
    }

    # Automatically use cookies.txt if it exists in the project root
    if os.path.exists("cookies.txt"):
        opts["cookiefile"] = "cookies.txt"

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
        opts.update(
            {"format": "best[filesize<=48M]/bestvideo[filesize<=48M]+bestaudio/best"}
        )

    return opts


# ==========================================
# 3. TELEGRAM HANDLERS
# ==========================================
def extract_url(text: str) -> str:
    """Finds the first link in a message, even without http://"""
    if not text:
        return None
    # Smarter Regex to catch links like www.instagram.com or tiktok.com
    match = re.search(
        r"((?:https?://)?(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*))",
        text,
    )

    if match:
        url = match.group(1)
        if not url.startswith("http"):
            url = "https://" + url  # yt-dlp requires https://
        return url
    return None


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Fixed Telegram Markdown (uses single asterisks instead of double)
    welcome_msg = (
        "🇬🇧 *Welcome to the Video Downloader Bot!*\n"
        "Send me any social media link (YouTube, Instagram, TikTok) to download it, even in groups.\n\n"
        "🇦🇫 *به ربات دانلود ویدیو خوش آمدید!*\n"
        "هر لینک شبکه اجتماعی را برای دانلود بفرستید، حتی در گروه ها."
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")


async def link_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Safely get the message (handles standard texts, edited texts, and channel posts)
        message = update.message or update.edited_message
        if not message:
            return

        user = update.effective_user

        # Look for links in BOTH standard text AND media captions
        text = message.text or message.caption
        url = extract_url(text)

        if not url:
            return  # Ignore messages that don't contain a link

        # Safely handle users who do not have a Telegram username set
        username = user.username if user and user.username else "Unknown"
        user_id = user.id if user else 0

        # Check anti-spam database
        if not check_spam_and_update(user_id, username):
            await message.reply_text(
                f"⏳ Wait {COOLDOWN_SECONDS}s. (صبر کنید)",
                reply_to_message_id=message.message_id,
            )
            return

        # Store long URL in memory, generate short ID for button
        task_id = str(uuid.uuid4())[:8]
        if "tasks" not in context.bot_data:
            context.bot_data["tasks"] = {}
        context.bot_data["tasks"][task_id] = url

        # Inline Keyboard with short ID and user ID
        keyboard = [
            [
                InlineKeyboardButton(
                    "🎬 Video (ویدیو)", callback_data=f"vid|{task_id}|{user_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "🎵 MP3 (صدا)", callback_data=f"aud|{task_id}|{user_id}"
                )
            ],
        ]
        await message.reply_text(
            "Choose format (فرمت را انتخاب کنید):",
            reply_markup=InlineKeyboardMarkup(keyboard),
            reply_to_message_id=message.message_id,
        )

    except Exception as e:
        # IF IT FAILS, THE BOT WILL NOW SEND YOU THE EXACT ERROR MESSAGE IN TELEGRAM
        error_text = f"⚠️ Internal Bot Error:\n{str(e)}"
        if update.message:
            await update.message.reply_text(error_text)
        print(error_text)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    clicker_id = query.from_user.id

    # Parse callback data
    req_type, task_id, original_user_id = query.data.split("|")

    # Verify clicker is the person who sent the link
    if str(clicker_id) != original_user_id:
        await query.answer("This is not your request! ❌", show_alert=True)
        return

    await query.answer()

    url = context.bot_data["tasks"].get(task_id)
    if not url:
        await query.edit_message_text("❌ Error: Task expired or link lost.")
        return

    chat_id = query.message.chat_id
    status_msg = await query.edit_message_text("⏳ Downloading... (در حال دانلود...)")

    file_id = f"{chat_id}_{int(time.time())}"
    raw_file = f"{file_id}.%(ext)s"

    try:
        opts = get_yt_dlp_options("audio" if req_type == "aud" else "video", raw_file)

        # Run yt_dlp without blocking the async event loop
        loop = asyncio.get_running_loop()

        def download_sync():
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return ydl.prepare_filename(info)

        downloaded_file = await loop.run_in_executor(None, download_sync)

        if req_type == "aud":
            downloaded_file = downloaded_file.rsplit(".", 1)[0] + ".mp3"

        # Compress if video is over 48MB
        if (
            req_type == "vid"
            and (os.path.getsize(downloaded_file) / (1024 * 1024)) > 48.0
        ):
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg.message_id,
                text="🗜 Compressing... (در حال فشرده سازی...)",
            )
            compressed_file = f"comp_{file_id}.mp4"
            await compress_video(downloaded_file, compressed_file)

            if os.path.exists(downloaded_file):
                os.remove(downloaded_file)
            downloaded_file = compressed_file

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

        await context.bot.delete_message(
            chat_id=chat_id, message_id=status_msg.message_id
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text="✅ Download finished! (دانلود با موفقیت انجام شد!)",
            reply_to_message_id=query.message.reply_to_message.message_id
            if query.message.reply_to_message
            else None,
        )

    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e).lower()
        if "sign in" in error_msg or "cookie" in error_msg:
            reply = (
                "⚠️ Authentication required. This video is age-restricted or private."
            )
        else:
            reply = "❌ Error downloading the media. The link might be invalid or unsupported."

        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=status_msg.message_id, text=reply
        )

    finally:
        # Cleanup memory and files
        context.bot_data["tasks"].pop(task_id, None)
        for f in os.listdir("."):
            if file_id in f and os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass


# ==========================================
# 4. WEB SERVER & CRONITOR
# ==========================================
async def health_check(request):
    return web.Response(text="Bot is running 24/7!")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Web server started on port {PORT}")


async def heartbeat_loop():
    """Runs continuously in the background to ping Cronitor."""
    if not CRONITOR_API_KEY:
        print("Cronitor API Key missing. Skipping heartbeat.")
        return

    cronitor.api_key = CRONITOR_API_KEY
    monitor = cronitor.Monitor("important-heartbeat")

    while True:
        try:
            # send a heartbeat event with a message and metrics
            monitor.ping(message="Alive!", metrics={"count": 100, "error_count": 3})
            print("Cronitor Heartbeat Sent")
        except Exception as e:
            print(f"Cronitor ping failed: {e}")

        await asyncio.sleep(300)  # Ping every 5 minutes


# ==========================================
# 5. MAIN ENTRYPOINT
# ==========================================
async def main():
    if os.path.exists("./ffmpeg"):
        os.chmod("./ffmpeg", os.stat("./ffmpeg").st_mode | stat.S_IEXEC)
    # -------------------------
    init_db()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(
        MessageHandler(
            (filters.TEXT | filters.CAPTION) & ~filters.COMMAND, link_received
        )
    )
    application.add_handler(CallbackQueryHandler(button_handler))

    # Start the web server (non-blocking)
    await start_web_server()

    # Start the Cronitor heartbeat loop as a background task
    asyncio.create_task(heartbeat_loop())

    # Run the bot loop natively
    async with application:
        await application.start()
        await application.updater.start_polling()
        # Keep the event loop running forever
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
