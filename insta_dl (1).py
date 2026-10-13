#!/usr/bin/env python3
"""
NOIR / REELS — minimal Telegram Instagram Reel downloader.

Requirements:
    python -m pip install -U python-telegram-bot yt-dlp

Run:
    export BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
    python bot.py

Optional:
    export DOWNLOAD_DIR="/tmp/noir-downloads"
    export MAX_UPLOAD_MB="49"
    export COOKIES_FILE="/path/to/instagram-cookies.txt"

Only download content you own or have permission to save. Instagram access
restrictions may prevent downloads; this bot does not bypass private access.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8509068048:AAGKxgNY5-YTDzKgZhXupxyN4uplIxq9Mmk").strip()
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", tempfile.gettempdir())) / "noir-reels"
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "49")) * 1024 * 1024
COOKIES_FILE = os.getenv("COOKIES_FILE", "").strip()
MIN_SIZE = 20 * 1024
URL_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)

logging.basicConfig(
    format="%(asctime)s  %(levelname)s  %(name)s  %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("noir-reels")

WELCOME = (
    "✦  <b>NOIR  /  REELS</b>\n"
    "<i>Instagram media downloader</i>\n\n"
    "Your media, simplified.\n"
    "Send an Instagram Reel link below and I'll process it when available.\n\n"
    "⌁ <b>Supported:</b> public Reel URLs\n"
    "◈ <b>Delivery:</b> video directly in this chat\n\n"
    "<i>Only save content you own or have permission to download.</i>"
)

KEYBOARD = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("⌘  How to use", callback_data="help"),
        InlineKeyboardButton("◈  About", callback_data="about"),
    ]
])


def is_instagram_reel_url(value: str) -> bool:
    """Accept Instagram Reel/post URLs only; reject unrelated hosts."""
    try:
        parsed = urlparse(value.strip().rstrip(".,!?)]}"))
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in ("http", "https"):
            return False
        if host not in {"instagram.com", "www.instagram.com", "m.instagram.com"}:
            return False
        return bool(re.match(r"^/(reel|reels|p)/[A-Za-z0-9_-]+/?$", parsed.path))
    except ValueError:
        return False


def safe_filename_from_url(url: str) -> str:
    match = re.search(r"/(?:reel|reels|p)/([A-Za-z0-9_-]+)", url)
    return match.group(1) if match else "instagram-video"


def download_with_ytdlp(url: str, output_dir: Path) -> Path:
    """Run yt-dlp safely without a shell and return the downloaded video path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(output_dir / "%(id)s.%(ext)s")

    command = [
        "yt-dlp",
        "--no-warnings",
        "--no-playlist",
        "--restrict-filenames",
        "--max-filesize", f"{MAX_UPLOAD_BYTES // (1024 * 1024)}M",
        "--merge-output-format", "mp4",
        "--format", "best[ext=mp4][vcodec!=none]/best[ext=mp4]/best",
        "--output", output_template,
        "--socket-timeout", "20",
        "--retries", "2",
        "--fragment-retries", "2",
        url,
    ]
    if COOKIES_FILE:
        cookie_path = Path(COOKIES_FILE)
        if cookie_path.is_file():
            command[1:1] = ["--cookies", str(cookie_path)]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        # Keep the useful error for logs, but don't expose arbitrary output to users.
        log.warning("yt-dlp failed: %s", (result.stderr or result.stdout)[-1800:])
        raise RuntimeError("Download provider could not retrieve this Reel.")

    candidates = [
        p for p in output_dir.iterdir()
        if p.is_file() and p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}
    ]
    if not candidates:
        raise RuntimeError("No video file was produced.")
    video = max(candidates, key=lambda p: p.stat().st_mtime)

    if video.stat().st_size < MIN_SIZE:
        raise RuntimeError("The downloaded file is too small to be a valid video.")
    if video.stat().st_size > MAX_UPLOAD_BYTES:
        raise RuntimeError(
            f"The video exceeds this bot's {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit."
        )
    return video


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(
            WELCOME,
            parse_mode="HTML",
            reply_markup=KEYBOARD,
            disable_web_page_preview=True,
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
        "⌘  <b>HOW TO USE</b>\n\n"
        "01  Open the Instagram Reel.\n"
        "02  Copy its link.\n"
        "03  Paste the link into this chat.\n"
        "04  Wait while the video is processed.\n\n"
        "— Public links work best.\n"
        "— Private, removed, age-restricted or login-gated content may fail.\n"
        "— Large videos may exceed Telegram's upload limit.\n"
        "— Never send your Instagram password to a bot."
    )
    if update.message:
        await update.message.reply_text(message, parse_mode="HTML", reply_markup=KEYBOARD)


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
        "◈  <b>ABOUT NOIR</b>\n\n"
        "A minimal Reel-saving assistant with a clean chat-first interface.\n\n"
        "⌁ Downloader: yt-dlp\n"
        "⌁ Delivery: Telegram chat\n"
        "⌁ Access: public or otherwise legitimately accessible content\n\n"
        "<i>Availability depends on Instagram and the source URL.</i>"
    )
    if update.message:
        await update.message.reply_text(message, parse_mode="HTML", reply_markup=KEYBOARD)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    if query.data == "help":
        text = (
            "⌘  <b>HOW TO USE</b>\n\n"
            "01  Copy an Instagram Reel link.\n"
            "02  Paste it into this chat.\n"
            "03  Wait for processing and delivery.\n\n"
            "<i>Public links work best. Private or restricted posts may fail.</i>"
        )
    else:
        text = (
            "◈  <b>NOIR / REELS</b>\n\n"
            "Minimal Instagram Reel downloader.\n"
            "Powered by yt-dlp; delivery via Telegram.\n\n"
            "<i>Save only content you own or have permission to download.</i>"
        )
    await query.message.reply_text(text, parse_mode="HTML", reply_markup=KEYBOARD)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.text:
        return

    match = URL_RE.search(message.text)
    if not match:
        await message.reply_text(
            "⌁  <b>Link needed</b>\n\nSend a valid Instagram Reel URL to begin.",
            parse_mode="HTML",
        )
        return

    url = match.group(0).rstrip(".,!?)]}")
    if not is_instagram_reel_url(url):
        await message.reply_text(
            "⌁  <b>Unsupported link</b>\n\n"
            "Please send a valid Instagram Reel URL, such as "
            "<code>https://www.instagram.com/reel/REEL_ID/</code>.",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return

    status = await message.reply_text(
        "◌  <b>Processing Reel</b>\n\n"
        "Checking the source and preparing your video…\n"
        "<i>This may take a little while.</i>",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    work_dir = Path(tempfile.mkdtemp(prefix="noir-"))
    try:
        await context.bot.send_chat_action(
            chat_id=message.chat_id,
            action=ChatAction.TYPING,
        )
        video_path = await asyncio.to_thread(download_with_ytdlp, url, work_dir)

        await status.edit_text(
            "✦  <b>Ready to deliver</b>\n\nUploading your video to this chat…",
            parse_mode="HTML",
        )
        await context.bot.send_chat_action(
            chat_id=message.chat_id,
            action=ChatAction.UPLOAD_VIDEO,
        )

        with video_path.open("rb") as video_file:
            await message.reply_video(
                video=video_file,
                caption=(
                    "✦  <b>NOIR  /  REELS</b>\n"
                    "━━━━━━━━━━━━━━\n"
                    "Your video is ready.\n"
                    f"⌁ Size: {video_path.stat().st_size / (1024 * 1024):.1f} MB"
                ),
                parse_mode="HTML",
                supports_streaming=True,
                read_timeout=120,
                write_timeout=120,
                connect_timeout=30,
            )
        await status.delete()

    except subprocess.TimeoutExpired:
        await status.edit_text(
            "⌁  <b>Timed out</b>\n\nThe source took too long to respond. Please try again later.",
            parse_mode="HTML",
        )
    except RuntimeError as exc:
        user_message = str(exc)
        if "provider could not retrieve" in user_message:
            user_message = (
                "Instagram did not provide an accessible video. The Reel may be private, "
                "restricted, removed, or require an authorized session. No download was completed."
            )
        await status.edit_text(
            "×  <b>Could not download this Reel</b>\n\n"
            f"{user_message}\n\n"
            "<i>Check the link and try again later.</i>",
            parse_mode="HTML",
        )
    except Exception:
        log.exception("Unexpected error while handling a Reel")
        try:
            await status.edit_text(
                "×  <b>Something went wrong</b>\n\n"
                "The video could not be delivered. Please try again later.",
                parse_mode="HTML",
            )
        except Exception:
            pass
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


async def post_init(application: Application) -> None:
    await application.bot.set_my_commands([
        ("start", "Open the Noir home screen"),
        ("help", "How to use the bot"),
        ("about", "About this bot"),
    ])


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit(
            "Missing BOT_TOKEN. Create a bot with @BotFather and set the BOT_TOKEN environment variable."
        )
    if not shutil.which("yt-dlp"):
        raise SystemExit(
            "yt-dlp is not installed. Install it with: python -m pip install -U yt-dlp"
        )

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    log.info("NOIR / REELS bot is starting")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
