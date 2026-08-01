# 🤖 Telegram Social Media Video Downloader Bot

A robust, asynchronous Telegram bot built with Python that downloads videos and audio from various social media platforms (Instagram, TikTok, X/Twitter, etc.) using `yt-dlp`. 

This bot is designed for continuous 24/7 deployment on cloud platforms like [Render](https://render.com), featuring an embedded web server to keep the application alive, on-the-fly video compression, and an SQLite-based anti-spam system.

## ✨ Features

* **Multi-Platform Support:** Download high-quality videos or extract MP3 audio from popular social media links.
* **Smart Compression:** Automatically detects files larger than Telegram's standard 50MB limit and compresses them via a statically linked FFmpeg binary.
* **Anti-Spam Protection:** Built-in SQLite database tracks user requests and applies a customizable cooldown period to prevent API abuse.
* **Cloud-Ready Keep-Alive:** Runs an asynchronous `aiohttp` web server on a designated port to satisfy PaaS health checks and prevent the bot from sleeping.
* **Inline Buttons:** Clean, interactive UI for users to choose between Video or Audio formats.
* **Cookie Support:** Seamlessly integrates with `cookies.txt` for platforms requiring authentication.

## 🚀 Prerequisites

If you are hosting this yourself or running it locally, you will need:
* **Python 3.9+**
* A Telegram Bot Token (from [@BotFather](https://t.me/botfather))
* **FFmpeg & FFprobe:** Linux binaries placed in the root directory (for server deployment).

## 🛠️ Local Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/tele-video-download-bot.git
   cd tele-video-download-bot
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Variables:**
   Create a `.env` file in the root directory and add your credentials:
   ```env
   BOT_TOKEN=your_telegram_bot_token_here
   PORT=10000
   ```

5. **Run the bot:**
   ```bash
   python bot.py
   ```

## ☁️ Deployment on Render.com

This bot is optimized to run as a **Web Service** on Render's free tier.

1. Create a new **Web Service** on Render and connect your GitHub repository.
2. **Build Command:** `pip install -r requirements.txt`
3. **Start Command:** `python bot.py`
4. **Environment Variables:** 
   * Add `BOT_TOKEN` with your Telegram token.
   * Add `PYTHON_VERSION` set to `3.10.0` (or your preferred version).
5. Deploy!

### ⏰ Preventing Render from Sleeping (Keep-Alive)
Render's free tier puts services to sleep after 15 minutes of inactivity. To keep your bot running 24/7:
1. Go to [cron-job.org](https://cron-job.org/) and create a free account.
2. Create a new cronjob.
3. Set the URL to your Render public address (e.g., `https://tele-video-download-bot.onrender.com/`).
4. Set the execution schedule to ping **Every 5 minutes**.

## 🍪 Advanced: Using Cookies

Some platforms restrict access without authentication. To bypass these limits:
1. Use a browser extension like *Get cookies.txt LOCALLY* to export your session cookies.
2. Ensure the file uses **LF (Unix) line endings**.
3. Save the file exactly as `cookies.txt` in the root directory of this project. The bot will automatically detect and apply it during downloads.

## 🔮 Future Development Roadmap

Contributions are welcome! Here are some planned features for future updates:
* **Dockerization:** Add a `Dockerfile` and `docker-compose.yml` to make self-hosting on VPS instances (like DigitalOcean or Hetzner) entirely plug-and-play.
* **Admin Dashboard:** Add Telegram commands (e.g., `/stats`, `/broadcast`) restricted to the bot owner to monitor usage and manage users directly from the chat.
* **Enhanced Proxy/IP Rotation:** Implement proxy support for `yt-dlp` to bypass aggressive data-center IP bans from specific platforms.
* **Playlist Support:** Allow users to download entire playlists or multi-image gallery posts and send them as Telegram media groups.
* **Localization:** Add a language selection menu to support more languages dynamically based on user preference.

## 📄 License

This project is open-source and available under the [MIT License](LICENSE). Feel free to fork, modify, and use it for your own projects!
