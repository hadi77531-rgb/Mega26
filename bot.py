#!/usr/bin/env python3
"""
============================================================
  Universal Media Downloader - Telegram Bot (2026 Edition)
============================================================
Supports: YouTube, Instagram, TikTok, Twitter/X, and 1000+ sites
Powered by: yt-dlp + pyTelegramBotAPI
============================================================
"""

import os
import re
import sys
import time
import shutil
import logging
import tempfile
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import telebot
from telebot import apihelper
from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from dotenv import load_dotenv

import yt_dlp

# ============================================================
#  ENVIRONMENT & CONFIGURATION
# ============================================================

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN is not set in .env file!")
    sys.exit(1)

# --- Proxy (essential for Iran / restricted networks) ---
PROXY_HTTP: str = os.getenv("PROXY_HTTP", "")
PROXY_HTTPS: str = os.getenv("PROXY_HTTPS", "")

# --- Proxy fallback: try proxy, fall back to direct if unavailable ---
PROXY_ENABLED = bool(PROXY_HTTP or PROXY_HTTPS)
_proxy_needs_fallback = False

logger = None  # Will be initialized in LOGGING section

if PROXY_ENABLED:
    proxy_dict: Dict[str, str] = {}
    if PROXY_HTTP:
        proxy_dict["http"] = PROXY_HTTP
    if PROXY_HTTPS:
        proxy_dict["https"] = PROXY_HTTPS

    # Test if proxy is actually reachable before committing to it
    try:
        import socket as _proxy_socket
        from urllib.parse import urlparse as _proxy_urlparse

        _test_url = PROXY_HTTPS or PROXY_HTTP
        _parsed = _proxy_urlparse(_test_url)
        _host = _parsed.hostname or "127.0.0.1"
        _port = _parsed.port or 1080
        _sock = _proxy_socket.socket(_proxy_socket.AF_INET, _proxy_socket.SOCK_STREAM)
        _sock.settimeout(3)
        _result = _sock.connect_ex((_host, _port))
        _sock.close()

        if _result == 0:
            apihelper.proxy = proxy_dict
            print(f"Proxy connected: {_host}:{_port}")
        else:
            print(f"WARNING: Proxy {_host}:{_port} is not reachable.")
            print("         Bot will run WITHOUT proxy (direct connection).")
            PROXY_ENABLED = False
            _proxy_needs_fallback = True
    except Exception as _e:
        print(f"WARNING: Proxy check failed: {_e}")
        print("         Bot will run WITHOUT proxy (direct connection).")
        PROXY_ENABLED = False
        _proxy_needs_fallback = True
else:
    print("No proxy configured. Using direct connection.")

# --- Cookie file for authenticated downloads ---
COOKIE_FILE: str = os.path.expanduser(
    os.getenv("COOKIE_FILE", "cookies.txt")
)

# --- YouTube Cookies from environment variable (for Railway/cloud) ---
# Set YOUTUBE_COOKIES env var with the full Netscape cookie text
YOUTUBE_COOKIES_TEXT: str = os.getenv("YOUTUBE_COOKIES", "")
_cookie_temp_file: Optional[str] = None

if YOUTUBE_COOKIES_TEXT:
    try:
        _cookie_temp_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, prefix="yt_cookies_"
        ).name
        with open(_cookie_temp_file, "w", encoding="utf-8") as f:
            f.write(YOUTUBE_COOKIES_TEXT)
        COOKIE_FILE = _cookie_temp_file
        print(f"YouTube cookies loaded from YOUTUBE_COOKIES env var -> {_cookie_temp_file}")
    except Exception as _e:
        print(f"WARNING: Failed to write cookie temp file: {_e}")

# --- Limits ---
MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
MAX_FILE_SIZE_BYTES: int = MAX_FILE_SIZE_MB * 1024 * 1024
RATE_LIMIT_WINDOW: int = int(os.getenv("RATE_LIMIT_WINDOW", "30"))
MAX_REQUESTS_PER_WINDOW: int = int(os.getenv("MAX_REQUESTS_PER_WINDOW", "5"))

# --- Paths ---
DOWNLOAD_DIR: str = os.path.expanduser(
    os.getenv("DOWNLOAD_DIR", "~/downloads")
)

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ============================================================
#  LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("MediaDownloaderBot")
logging.getLogger("yt_dlp").setLevel(logging.WARNING)

# ============================================================
#  FFMPEG CHECK
# ============================================================

FFMPEG_AVAILABLE: bool = shutil.which("ffmpeg") is not None
if not FFMPEG_AVAILABLE:
    logger.warning(
        "ffmpeg NOT found! Audio extraction & format merging will fail. "
        "Install: sudo apt install ffmpeg (Linux) or brew install ffmpeg (macOS)"
    )
else:
    logger.info(f"ffmpeg found at: {shutil.which('ffmpeg')}")

# ============================================================
#  BOT INITIALIZATION
# ============================================================

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# Ensure webhook is removed for polling
try:
    bot.remove_webhook()
except Exception:
    pass

# ============================================================
#  DATA STRUCTURES (Thread-Safe)
# ============================================================

user_states: Dict[int, Dict[str, Any]] = {}
_states_lock = threading.Lock()

rate_limit_map: Dict[int, list] = {}
_rate_lock = threading.Lock()


def cleanup_stale_states(max_age_seconds: int = 1800) -> None:
    """Remove user states older than max_age_seconds (default 30 min)."""
    now = datetime.now()
    with _states_lock:
        stale = [
            cid
            for cid, s in user_states.items()
            if (now - s.get("timestamp", now)).total_seconds() > max_age_seconds
        ]
        for cid in stale:
            dp = user_states[cid].get("download_path", "")
            if dp and os.path.exists(dp):
                try:
                    os.remove(dp)
                except OSError:
                    pass
            del user_states[cid]
    if stale:
        logger.info(f"Cleaned up {len(stale)} stale user states")


def check_rate_limit(chat_id: int) -> bool:
    """Return True if user is within rate limit, False if throttled."""
    now = datetime.now()
    with _rate_lock:
        if chat_id not in rate_limit_map:
            rate_limit_map[chat_id] = []
        rate_limit_map[chat_id] = [
            t for t in rate_limit_map[chat_id]
            if (now - t).total_seconds() < RATE_LIMIT_WINDOW
        ]
        if len(rate_limit_map[chat_id]) >= MAX_REQUESTS_PER_WINDOW:
            return False
        rate_limit_map[chat_id].append(now)
        return True


# ============================================================
#  URL VALIDATION
# ============================================================

SUPPORTED_DOMAINS = re.compile(
    r"https?://("
    r"(www\.)?(youtube\.com|youtu\.be|m\.youtube\.com)"
    r"|(www\.)?(instagram\.com)"
    r"|(www\.)?(tiktok\.com|vm\.tiktok\.com|vt\.tiktok\.com)"
    r"|(www\.)?(twitter\.com|x\.com)"
    r"|(www\.)?(vimeo\.com)"
    r"|(www\.)?(facebook\.com|fb\.watch)"
    r"|(www\.)?(reddit\.com)"
    r"|(www\.)?(twitch\.tv)"
    r"|(www\.)?(dailymotion\.com)"
    r"|(www\.)?(bilibili\.com)"
    r")",
    re.IGNORECASE,
)

GENERIC_URL = re.compile(r"https?://[^\s]+", re.IGNORECASE)


def validate_url(url: str) -> bool:
    """Check if the URL is plausibly valid."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if SUPPORTED_DOMAINS.match(url):
        return True
    if GENERIC_URL.match(url):
        return True
    return False


def normalize_url(url: str) -> str:
    """Normalize URL: strip spaces, ensure scheme."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


# ============================================================
#  YT-DLP CONFIGURATION (2026 Anti-Bot Bypass)
# ============================================================

# YouTube player clients to try, in order of reliability.
# Each attempt uses a different client to avoid the bot detection.
YOUTUBE_PLAYER_CLIENTS = [
    # Order: start with clients least likely to trigger bot detection
    ["web_creator", "web", "mweb"],
    ["web", "mweb"],
    ["android"],
    ["ios"],
]

# User agents matching each client type
_USER_AGENTS = {
    "web_creator": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/137.0.0.0 Safari/537.36"
    ),
    "web": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/137.0.0.0 Safari/537.36"
    ),
    "mweb": (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/137.0.0.0 Mobile Safari/537.36"
    ),
    "android": (
        "com.google.android.youtube/19.09.37 (Linux; U; Android 14; en_US; "
        "Pixel 8 Pro; Build/UP1A.231105.001) gzip"
    ),
    "ios": (
        "com.google.ios.youtube/19.09.3 (iPhone14,3; U; CPU iOS 17_4 like Mac OS X; en_US)"
    ),
}


def _is_youtube_url(url: str) -> bool:
    """Check if URL is a YouTube URL."""
    return bool(re.search(
        r"(youtube\.com|youtu\.be|m\.youtube\.com)", url, re.IGNORECASE
    ))


def build_ydl_opts(
    media_type: str,
    quality: str,
    output_dir: str = DOWNLOAD_DIR,
    client_index: int = 0,
) -> Dict[str, Any]:
    """Build yt-dlp options optimized for 2026 anti-bot bypass.

    Args:
        client_index: Which player client set to use (for retry logic).
    """
    # Pick player clients for this attempt
    clients = YOUTUBE_PLAYER_CLIENTS[
        min(client_index, len(YOUTUBE_PLAYER_CLIENTS) - 1)
    ]
    primary_client = clients[0]
    ua = _USER_AGENTS.get(primary_client, _USER_AGENTS["web"])

    opts: Dict[str, Any] = {
        "outtmpl": os.path.join(output_dir, "%(title).100s_%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "ignoreerrors": True,
        "socket_timeout": 30,
        "retries": 5,
        "fragment_retries": 5,
        # 2026 YouTube anti-bot: try multiple player clients
        "extractor_args": {
            "youtube": {
                "player_client": clients,
            }
        },
        "user_agent": ua,
        # Bypass some bot detection checks
        "http_headers": {
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Ch-Ua-Platform": '"Windows"',
        },
    }

    # --- Proxy for yt-dlp ---
    yt_proxy = os.getenv("YTDLP_PROXY", "")
    if yt_proxy:
        opts["proxy"] = yt_proxy

    # --- Cookies ---
    if os.path.exists(COOKIE_FILE):
        opts["cookiefile"] = COOKIE_FILE
        logger.info(f"Using cookies from: {COOKIE_FILE}")
    else:
        logger.info("No cookie file found; public content only.")

    # --- Media type specific ---
    if media_type == "audio":
        opts["format"] = "bestaudio/best"
        if FFMPEG_AVAILABLE:
            opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": quality,
                }
            ]
        else:
            opts["format"] = "bestaudio[ext=m4a]/bestaudio"
    else:
        # Video: robust format selection with many fallbacks
        # Some videos don't have matching height — always end with 'best'
        height = quality
        opts["format"] = (
            f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
            f"bestvideo[height<={height}]+bestaudio/"
            f"bestvideo[height<={height}]/"
            f"bestvideo+bestaudio/"
            f"best[height<={height}]/"
            f"bestvideo/best"
        )
        opts["merge_output_format"] = "mp4"
        # Don't fail if no exact format match — fall through to best
        opts["ignore_no_formats_error"] = True

    opts["progress_hooks"] = []  # injected per-download
    return opts


# ============================================================
#  PROGRESS HANDLING
# ============================================================

def make_progress_hook(chat_id: int, status_message_id: int):
    """Create a progress hook that updates the Telegram status message."""
    last_update_time = [0.0]

    def progress_hook(d: dict) -> None:
        now = time.time()
        if now - last_update_time[0] < 2.0:
            return
        last_update_time[0] = now

        status = d.get("status", "")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            speed = d.get("speed") or 0
            eta = d.get("eta") or 0
            percent = d.get("_percent_str", "0%").strip()

            if total > 0:
                pct = int(downloaded / total * 100)
                bar = _make_bar(pct)
                size_mb = total / (1024 * 1024)
                speed_str = (
                    f"{speed / 1024 / 1024:.1f} MB/s"
                    if speed else "calculating..."
                )
                eta_str = str(timedelta(seconds=eta)) if eta else "..."
                text = (
                    f"<b>Downloading...</b>\n\n"
                    f"{bar} <b>{percent}</b>\n"
                    f"Size: <code>{size_mb:.1f} MB</code>\n"
                    f"Speed: <code>{speed_str}</code>\n"
                    f"ETA: <code>{eta_str}</code>"
                )
                _safe_edit(chat_id, status_message_id, text)

        elif status == "finished":
            _safe_edit(
                chat_id, status_message_id,
                "<b>Processing...</b>\nMerging formats & converting...",
            )

    return progress_hook


def _make_bar(percent: int, length: int = 14) -> str:
    """Create a unicode progress bar."""
    filled = int(length * percent / 100)
    empty = length - filled
    return "\u2595" + "\u25B0" * filled + "\u25B1" * empty + "\u258f"


def _safe_edit(chat_id: int, message_id: int, text: str) -> None:
    """Edit message safely; ignore if message unchanged or deleted."""
    try:
        bot.edit_message_text(
            text, chat_id=chat_id, message_id=message_id, parse_mode="HTML",
        )
    except Exception:
        pass


# ============================================================
#  FILE SENDING WITH SIZE CHECK
# ============================================================

def send_file_safely(
    chat_id: int, file_path: str, media_type: str, title: str = "Unknown",
) -> bool:
    """Send file to user with size validation. Returns True on success."""
    file_size = os.path.getsize(file_path)

    if file_size > MAX_FILE_SIZE_BYTES:
        size_mb = file_size / (1024 * 1024)
        bot.send_message(
            chat_id,
            (
                f"<b>File too large!</b>\n\n"
                f"Size: <code>{size_mb:.1f} MB</code>\n"
                f"Telegram limit: <code>{MAX_FILE_SIZE_MB} MB</code>\n\n"
                f"<i>Try a lower quality or audio-only format.</i>"
            ),
        )
        return False

    try:
        with open(file_path, "rb") as f:
            if media_type == "audio":
                bot.send_audio(chat_id, f, title=title[:64], timeout=120)
            else:
                bot.send_video(
                    chat_id, f,
                    caption=f"{title[:200]}",
                    timeout=120,
                    supports_streaming=True,
                )
        return True
    except Exception as e:
        logger.error(f"Failed to send file to {chat_id}: {e}")
        bot.send_message(
            chat_id,
            f"<b>Failed to send file.</b>\n<code>{str(e)[:500]}</code>",
        )
        return False


# ============================================================
#  YOUTUBE DOWNLOAD WITH RETRY (Anti-Bot Bypass)
# ============================================================

def _try_download_youtube(
    url: str, ydl_opts_base: Dict[str, Any], progress_hook, media_type: str
) -> tuple:
    """Try downloading YouTube URL with multiple player client fallbacks.

    Returns: (info_dict, file_path, video_title)
    Raises: last exception if all attempts fail.
    """
    last_error = None

    for attempt, clients in enumerate(YOUTUBE_PLAYER_CLIENTS):
        client_name = clients[0]
        logger.info(
            f"YouTube attempt {attempt + 1}/{len(YOUTUBE_PLAYER_CLIENTS)}: "
            f"player_client={clients}"
        )

        # Build fresh opts for each attempt (don't mutate the base)
        opts = dict(ydl_opts_base)
        opts["extractor_args"] = {"youtube": {"player_client": clients}}
        opts["user_agent"] = _USER_AGENTS.get(
            client_name, _USER_AGENTS["web"]
        )
        opts["progress_hooks"] = [progress_hook]

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)

                if info is None:
                    raise ValueError("yt-dlp returned no info")

                # Determine file path
                file_path = _determine_file_path(ydl, info, media_type)
                video_title = (
                    info.get("title")
                    or info.get("fulltitle")
                    or info.get("alt_title")
                    or "Unknown"
                )

                if file_path and os.path.exists(file_path):
                    return info, file_path, video_title
                else:
                    raise FileNotFoundError(
                        f"Downloaded file not found: {file_path}"
                    )

        except Exception as e:
            last_error = e
            error_str = str(e)

            # If it's a bot detection error, try next client
            if any(
                keyword in error_str.lower()
                for keyword in [
                    "sign in to confirm",
                    "not a bot",
                    "returned no info",
                    "po token",
                    "video unavailable",
                    "sign in",
                ]
            ):
                logger.warning(
                    f"YouTube bot detection on client {client_name}, "
                    f"trying next... ({error_str[:200]})"
                )
                continue
            else:
                # Non-bot-detection error, don't retry with different clients
                raise

    # All attempts failed
    raise last_error


def _determine_file_path(
    ydl: yt_dlp.YoutubeDL, info: dict, media_type: str
) -> Optional[str]:
    """Determine the downloaded file path from yt-dlp info dict."""
    file_path = None

    if "requested_downloads" in info and info["requested_downloads"]:
        file_path = info["requested_downloads"][0].get("filepath", "")
    elif "requested_formats" in info and info["requested_formats"]:
        file_path = ydl.prepare_filename(info)
    else:
        file_path = ydl.prepare_filename(info)

    # Fix extension for audio post-processing
    if media_type == "audio" and file_path:
        base = os.path.splitext(file_path)[0]
        for ext in (".mp3", ".m4a", ".opus", ".aac", ".webm"):
            candidate = base + ext
            if os.path.exists(candidate):
                file_path = candidate
                break

    return file_path


# ============================================================
#  MAIN DOWNLOAD LOGIC
# ============================================================

def download_and_send(chat_id: int, status_msg_id: int) -> None:
    """Orchestrate: download -> validate -> send -> cleanup."""
    with _states_lock:
        state = user_states.get(chat_id, {}).copy()

    url = state.get("url", "")
    media_type = state.get("media_type", "video")
    quality = state.get("quality", "720")

    if not url:
        _safe_edit(chat_id, status_msg_id, "Session expired. Send a new link.")
        return

    ydl_opts_base = build_ydl_opts(media_type, quality)
    progress_hook = make_progress_hook(chat_id, status_msg_id)

    file_path: Optional[str] = None
    video_title: str = "Unknown"

    try:
        if _is_youtube_url(url):
            # Use retry logic with multiple player clients
            _, file_path, video_title = _try_download_youtube(
                url, ydl_opts_base, progress_hook, media_type
            )
        else:
            # Non-YouTube: standard download (no retry needed)
            ydl_opts_base["progress_hooks"] = [progress_hook]
            with yt_dlp.YoutubeDL(ydl_opts_base) as ydl:
                info = ydl.extract_info(url, download=True)

                if info is None:
                    raise ValueError("yt-dlp returned no info")

                file_path = _determine_file_path(ydl, info, media_type)
                video_title = (
                    info.get("title")
                    or info.get("fulltitle")
                    or info.get("alt_title")
                    or "Unknown"
                )

                if not file_path or not os.path.exists(file_path):
                    raise FileNotFoundError(
                        f"Downloaded file not found: {file_path}"
                    )

        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)

        _safe_edit(
            chat_id, status_msg_id,
            f"<b>Download complete!</b>\n"
            f"Size: <code>{file_size_mb:.1f} MB</code>\n"
            f"<b>Sending to Telegram...</b>",
        )

        success = send_file_safely(chat_id, file_path, media_type, video_title)

        if success:
            bot.send_message(
                chat_id,
                (
                    f"<b>Done!</b>\n\n"
                    f"Title: {video_title[:200]}\n"
                    f"Size: <code>{file_size_mb:.1f} MB</code>\n"
                    f"Quality: <code>{quality}</code>\n\n"
                    f"Send another link for a new download."
                ),
            )

    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)[:800]
        logger.error(f"yt-dlp error for {chat_id}: {error_msg}")
        _safe_edit(
            chat_id, status_msg_id,
            (
                f"<b>Download failed.</b>\n\n"
                f"<code>{error_msg}</code>\n\n"
                f"<i>Try a different quality, or add YouTube cookies "
                f"via YOUTUBE_COOKIES env var for better results.</i>"
            ),
        )
    except FileNotFoundError as e:
        logger.error(f"File error for {chat_id}: {e}")
        _safe_edit(
            chat_id, status_msg_id,
            f"<b>File error:</b> <code>{str(e)[:500]}</code>",
        )
    except Exception as e:
        logger.error(f"Unexpected error for {chat_id}: {e}", exc_info=True)
        _safe_edit(
            chat_id, status_msg_id,
            f"<b>Unexpected error:</b>\n<code>{str(e)[:500]}</code>",
        )
    finally:
        # Cleanup downloaded file
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError as e:
                logger.warning(f"Could not delete {file_path}: {e}")

        # Clean orphaned files
        _cleanup_download_dir()


def _cleanup_download_dir() -> None:
    """Remove orphaned files older than 1 hour."""
    try:
        now = time.time()
        for fname in os.listdir(DOWNLOAD_DIR):
            fpath = os.path.join(DOWNLOAD_DIR, fname)
            if os.path.isfile(fpath):
                if now - os.path.getmtime(fpath) > 3600:
                    try:
                        os.remove(fpath)
                    except OSError:
                        pass
    except Exception:
        pass


# ============================================================
#  BOT HANDLERS
# ============================================================

@bot.message_handler(commands=["start", "help"])
def handle_start(message: telebot.types.Message) -> None:
    """Welcome message with usage instructions."""
    chat_id = message.chat.id

    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("Supported Sites", callback_data="info_sites"),
        InlineKeyboardButton("How to Use", callback_data="info_usage"),
        InlineKeyboardButton("Cookie Setup", callback_data="info_cookies"),
    )

    cookies_status = "Enabled" if os.path.exists(COOKIE_FILE) else "Not configured"
    ffmpeg_status = "Ready" if FFMPEG_AVAILABLE else "MISSING"

    bot.send_message(
        chat_id,
        (
            f"<b>Welcome to Universal Media Downloader!</b>\n\n"
            f"I can download from <b>YouTube, Instagram, TikTok, Twitter/X</b> "
            f"and <b>1000+</b> other sites.\n\n"
            f"<b>Just send me a link to get started!</b>\n\n"
            f"Max file size: <code>{MAX_FILE_SIZE_MB} MB</code>\n"
            f"Cookies: <code>{cookies_status}</code>\n"
            f"FFmpeg: <code>{ffmpeg_status}</code>"
        ),
        reply_markup=markup,
    )


@bot.message_handler(commands=["status"])
def handle_status(message: telebot.types.Message) -> None:
    """Show bot health status."""
    chat_id = message.chat.id
    with _states_lock:
        active_sessions = len(user_states)

    cookies_status = (
        f"Present: {COOKIE_FILE}" if os.path.exists(COOKIE_FILE)
        else "Not found"
    )
    proxy_status = (
        "Connected" if (PROXY_ENABLED and not _proxy_needs_fallback)
        else "Fallback (direct)" if _proxy_needs_fallback
        else "Not set"
    )
    ffmpeg_status = "Present" if FFMPEG_AVAILABLE else "MISSING"

    status_text = (
        f"<b>Bot Status</b>\n\n"
        f"Bot: <b>Online</b>\n"
        f"Active sessions: <code>{active_sessions}</code>\n"
        f"FFmpeg: <code>{ffmpeg_status}</code>\n"
        f"Cookies: <code>{cookies_status}</code>\n"
        f"Proxy: <code>{proxy_status}</code>\n"
        f"Download dir: <code>{DOWNLOAD_DIR}</code>\n"
    )
    bot.send_message(chat_id, status_text)


@bot.callback_query_handler(func=lambda call: call.data.startswith("info_"))
def handle_info_callbacks(call: telebot.types.CallbackQuery) -> None:
    """Handle info button callbacks."""
    chat_id = call.message.chat.id
    data = call.data

    if data == "info_sites":
        text = (
            "<b>Supported Sites (partial list):</b>\n\n"
            "- YouTube (videos, Shorts)\n"
            "- Instagram (posts, Reels, Stories*)\n"
            "- TikTok (videos)\n"
            "- Twitter/X (videos)\n"
            "- Facebook (videos)\n"
            "- Vimeo, Dailymotion, Twitch\n"
            "- Reddit, Bilibili, and 1000+ more\n\n"
            "<i>* Requires cookies for private/authenticated content.</i>"
        )
    elif data == "info_usage":
        text = (
            "<b>How to Use:</b>\n\n"
            "1. Send any video URL\n"
            "2. Choose Video or Audio\n"
            "3. Select quality\n"
            "4. Wait for download & delivery\n\n"
            "<b>Commands:</b>\n"
            "/start - Show welcome message\n"
            "/status - Bot health check\n\n"
            f"<b>Limits:</b> {MAX_FILE_SIZE_MB} MB per file\n"
            f"<b>Rate limit:</b> {MAX_REQUESTS_PER_WINDOW} per {RATE_LIMIT_WINDOW}s"
        )
    elif data == "info_cookies":
        text = (
            "<b>Cookie Setup Guide:</b>\n\n"
            "For private Instagram, age-restricted YouTube, etc.\n\n"
            "<b>Method 1 - Browser Extension:</b>\n"
            "Install 'Get cookies.txt LOCALLY' (Chrome/Firefox)\n"
            "- Visit the site & log in\n"
            "- Export cookies.txt\n"
            "- Place it at: ./cookies.txt\n\n"
            "<b>Method 2 - Environment Variable (Railway):</b>\n"
            "Set YOUTUBE_COOKIES in Railway env vars\n"
            "with the full cookies.txt content\n\n"
            "<b>Method 3 - yt-dlp command:</b>\n"
            "yt-dlp --cookies-from-browser chrome URL"
        )
    else:
        text = "Unknown info."

    try:
        bot.edit_message_text(text, chat_id, call.message.message_id, parse_mode="HTML")
        back_markup = InlineKeyboardMarkup()
        back_markup.add(
            InlineKeyboardButton("Back to Menu", callback_data="info_back")
        )
        bot.edit_message_reply_markup(
            chat_id, call.message.message_id, reply_markup=back_markup
        )
    except Exception:
        pass

    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "info_back")
def handle_back(call: telebot.types.CallbackQuery) -> None:
    """Return to the main info menu."""
    chat_id = call.message.chat.id
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("Supported Sites", callback_data="info_sites"),
        InlineKeyboardButton("How to Use", callback_data="info_usage"),
        InlineKeyboardButton("Cookie Setup", callback_data="info_cookies"),
    )
    try:
        bot.edit_message_text(
            "<b>Universal Media Downloader</b>\n\nSelect a topic to learn more:",
            chat_id,
            call.message.message_id,
            parse_mode="HTML",
            reply_markup=markup,
        )
    except Exception:
        pass
    bot.answer_callback_query(call.id)


@bot.message_handler(func=lambda message: True)
def handle_link(message: telebot.types.Message) -> None:
    """Main handler - receive URL from user and show format picker."""
    chat_id = message.chat.id
    url = message.text.strip() if message.text else ""

    # Rate limit check
    if not check_rate_limit(chat_id):
        bot.reply_to(
            message,
            f"<b>Slow down!</b> Max {MAX_REQUESTS_PER_WINDOW} downloads "
            f"per {RATE_LIMIT_WINDOW} seconds.\nPlease wait...",
        )
        return

    # Cleanup stale states
    cleanup_stale_states()

    # Validate URL
    if not validate_url(url):
        bot.reply_to(
            message,
            (
                "<b>Invalid or unsupported URL.</b>\n\n"
                "Please send a direct link to a video/post from:\n"
                "- YouTube, Instagram, TikTok, Twitter/X\n"
                "- Vimeo, Facebook, Dailymotion, etc.\n\n"
                "Example:\n<code>https://www.youtube.com/watch?v=dQw4w9WgXcQ</code>"
            ),
        )
        return

    url = normalize_url(url)

    # Store state
    with _states_lock:
        user_states[chat_id] = {
            "url": url,
            "timestamp": datetime.now(),
            "download_path": None,
        }

    # Build quality selector
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("Video", callback_data="type_video"),
        InlineKeyboardButton("Audio (MP3)", callback_data="type_audio"),
    )

    display_url = url[:100] + ("..." if len(url) > 100 else "")
    bot.reply_to(
        message,
        (
            f"<b>Link received!</b>\n"
            f"<code>{display_url}</code>\n\n"
            f"<b>Choose output format:</b>"
        ),
        reply_markup=markup,
    )


# ============================================================
#  CALLBACK HANDLERS - TYPE & QUALITY SELECTION
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("type_"))
def handle_type_selection(call: telebot.types.CallbackQuery) -> None:
    """User selected Video or Audio - show quality options."""
    chat_id = call.message.chat.id
    data = call.data

    with _states_lock:
        if chat_id not in user_states:
            bot.answer_callback_query(
                call.id, "Session expired. Send a new link."
            )
            return

    if data == "type_video":
        with _states_lock:
            user_states[chat_id]["media_type"] = "video"

        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("480p", callback_data="q_480"),
            InlineKeyboardButton("720p", callback_data="q_720"),
            InlineKeyboardButton("1080p", callback_data="q_1080"),
            InlineKeyboardButton("1440p (2K)", callback_data="q_1440"),
            InlineKeyboardButton("2160p (4K)", callback_data="q_2160"),
            InlineKeyboardButton("Back", callback_data="type_back"),
        )
        bot.edit_message_text(
            "<b>Video</b> - Select quality:",
            chat_id, call.message.message_id, reply_markup=markup,
        )

    elif data == "type_audio":
        with _states_lock:
            user_states[chat_id]["media_type"] = "audio"

        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("MP3 128 kbps", callback_data="q_128"),
            InlineKeyboardButton("MP3 192 kbps", callback_data="q_192"),
            InlineKeyboardButton("MP3 256 kbps", callback_data="q_256"),
            InlineKeyboardButton("MP3 320 kbps", callback_data="q_320"),
            InlineKeyboardButton("Back", callback_data="type_back"),
        )
        bot.edit_message_text(
            "<b>Audio (MP3)</b> - Select quality:",
            chat_id, call.message.message_id, reply_markup=markup,
        )

    elif data == "type_back":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("Video", callback_data="type_video"),
            InlineKeyboardButton("Audio (MP3)", callback_data="type_audio"),
        )
        bot.edit_message_text(
            "<b>Choose output format:</b>",
            chat_id, call.message.message_id, reply_markup=markup,
        )

    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("q_"))
def handle_quality_selection(call: telebot.types.CallbackQuery) -> None:
    """User selected quality - start download."""
    chat_id = call.message.chat.id
    quality = call.data.split("_", 1)[1]

    with _states_lock:
        if chat_id not in user_states:
            bot.answer_callback_query(
                call.id, "Session expired. Send a new link."
            )
            return
        user_states[chat_id]["quality"] = quality
        media_type = user_states[chat_id].get("media_type", "video")

    quality_label = (
        f"{quality} kbps" if media_type == "audio" else f"{quality}p"
    )
    media_label = "Audio" if media_type == "audio" else "Video"

    bot.edit_message_text(
        f"<b>Starting download...</b>\n\n"
        f"Type: <b>{media_label}</b>\n"
        f"Quality: <code>{quality_label}</code>\n\n"
        f"<i>Please wait...</i>",
        chat_id, call.message.message_id,
    )

    bot.answer_callback_query(call.id)

    # Fire download in a background thread
    thread = threading.Thread(
        target=download_and_send,
        args=(chat_id, call.message.message_id),
        daemon=True,
    )
    thread.start()


# ============================================================
#  SAFE POLLING WITH AUTO-RESTART
# ============================================================

def safe_polling() -> None:
    """Run bot polling with automatic restart on errors."""
    logger.info("Bot is starting...")
    while True:
        try:
            bot.infinity_polling(
                timeout=60,
                long_polling_timeout=30,
                logger_level=logging.WARNING,
            )
        except KeyboardInterrupt:
            logger.info("Bot stopped by user.")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Polling error: {e}", exc_info=True)
            logger.info("Restarting in 10 seconds...")
            time.sleep(10)


# ============================================================
#  ENTRY POINT
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("  Universal Media Downloader Bot")
    print("  yt-dlp + Telegram - 2026 Edition")
    print("=" * 50)
    logger.info(f"Download directory: {DOWNLOAD_DIR}")
    logger.info(
        f"Cookie file: {COOKIE_FILE} "
        f"{'(found)' if os.path.exists(COOKIE_FILE) else '(not found)'}"
    )
    logger.info(
        f"Proxy: {'Connected' if (PROXY_ENABLED and not _proxy_needs_fallback) else 'Fallback/direct' if _proxy_needs_fallback else 'Not configured'}"
    )
    logger.info(f"FFmpeg: {'Available' if FFMPEG_AVAILABLE else 'MISSING'}")
    logger.info(f"Max file size: {MAX_FILE_SIZE_MB} MB")
    logger.info(
        f"Rate limit: {MAX_REQUESTS_PER_WINDOW} req/{RATE_LIMIT_WINDOW}s"
    )

    safe_polling()
