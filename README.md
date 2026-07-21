# Universal Media Downloader — Telegram Bot

A production-ready Telegram bot that downloads videos and audio from YouTube, Instagram, TikTok, Twitter/X, and 1000+ other sites using yt-dlp.

---

## Features (Compared to Original)

| Feature | Original Code | Improved Version |
|---|---|---|
| HTML escaping | ❌ Broken (`&lt;` `&gt;` everywhere) | ✅ Clean, valid HTML |
| Environment variables | ❌ Token hardcoded | ✅ `.env` file |
| Proxy support | ❌ None | ✅ HTTP + SOCKS5 (separate for Telegram & yt-dlp) |
| Cookie support | ❌ None | ✅ Netscape cookies.txt |
| File size check | ❌ None | ✅ Warns/aborts if > limit |
| Progress bar | ❌ None | ✅ Real-time live progress in chat |
| URL validation | ❌ Any text accepted | ✅ Regex validation |
| Error handling | ❌ Fragile | ✅ Per-error-type handling + cleanup |
| Rate limiting | ❌ None | ✅ Configurable per-user throttle |
| Logging | ❌ `print()` only | ✅ File + console, leveled |
| Memory management | ❌ Leaked forever | ✅ Auto-cleanup stale states |
| Thread safety | ❌ None | ✅ Locks on shared state |
| Quality options | ❌ 3 video / 1 audio | ✅ 5 video (480p-4K) / 4 audio (128-320kbps) |
| File cleanup | ❌ Only on success | ✅ Always (finally block + orphan scan) |
| Info/help system | ❌ None | ✅ Interactive menus + /status command |
| 2026 YouTube support | ❌ Fails on SABR | ✅ extractor_args bypass |
| User-agent spoofing | ❌ Default | ✅ Real Chrome UA |
| Polling resilience | ❌ Crashes on error | ✅ Auto-restart with delay |

---

## Quick Start

### 1. Prerequisites

```bash
# Install system dependencies
# Linux (Debian/Ubuntu):
sudo apt update
sudo apt install ffmpeg python3 python3-pip python3-venv -y

# macOS:
brew install ffmpeg python3

# Windows:
# Download ffmpeg from https://ffmpeg.org/download.html
# Install Python from https://python.org
```

### 2. Clone & Setup

```bash
cd ~/downloader_bot

# Create virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows

# Install Python dependencies
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
# Copy example env file
cp .env.example .env

# Edit with your values
nano .env
```

**Minimum required:**
```
BOT_TOKEN=123456:ABC-DEF1234ghijk
```

**With proxy (Iran users):**
```
BOT_TOKEN=123456:ABC-DEF1234ghijk
PROXY_HTTP=socks5://127.0.0.1:1080
PROXY_HTTPS=socks5://127.0.0.1:1080
YTDLP_PROXY=socks5://127.0.0.1:1080
```

**Proxy formats supported:**
- `socks5://127.0.0.1:1080` (SOCKS5, e.g., v2rayN, Shadowsocks)
- `socks5://user:pass@host:port` (Authenticated SOCKS5)
- `http://127.0.0.1:8080` (HTTP proxy)
- `https://user:pass@host:8080` (HTTPS proxy)

### 4. Get Your Bot Token

1. Open Telegram, search for `@BotFather`
2. Send `/newbot`
3. Follow the prompts to create a bot
4. Copy the token (looks like `1234567890:AAFfjks...`)
5. Paste it into your `.env` file

### 5. (Recommended) Set Up Cookies

For Instagram, age-restricted YouTube, and private content:

**Method A — Browser Extension (easiest):**
1. Install "Get cookies.txt LOCALLY" extension (Chrome/Edge/Firefox)
2. Log in to Instagram / YouTube in your browser
3. Click the extension → Export cookies.txt
4. Place `cookies.txt` in the bot directory

**Method B — yt-dlp command:**
```bash
yt-dlp --cookies-from-browser chrome --cookies cookies.txt
```

### 6. Run the Bot

```bash
# Make sure venv is active
source venv/bin/activate

# Run
python bot.py
```

For production, use a process manager:

```bash
# Using systemd (Linux):
sudo nano /etc/systemd/system/media-downloader-bot.service

# Using tmux/screen:
tmux new -s bot
python bot.py
# Ctrl+B, D to detach

# Using nohup:
nohup python bot.py > bot.out 2>&1 &
```

---

## Usage

1. **Start chat**: Send `/start` to the bot
2. **Send a link**: Paste any video URL (YouTube, Instagram, TikTok, etc.)
3. **Choose format**: Tap "Video" or "Audio (MP3)"
4. **Choose quality**: Select resolution/bitrate
5. **Wait**: Progress bar shows real-time status
6. **Receive file**: Bot sends the video/audio directly

**Commands:**
- `/start` — Welcome message with interactive menu
- `/status` — Bot health check (sessions, cookies, ffmpeg, proxy)

---

## Supported Sites (1800+)

| Platform | Public | Private/Age-restricted |
|---|---|---|
| YouTube | ✅ | ✅ (with cookies) |
| Instagram Reels | ✅ | ✅ (with cookies) |
| Instagram Posts | ✅ | ✅ (with cookies) |
| TikTok | ✅ | N/A |
| Twitter/X | ✅ | N/A |
| Facebook | ✅ | ✅ (with cookies) |
| Vimeo | ✅ | N/A |
| Reddit | ✅ | N/A |
| Twitch | ✅ | N/A |

---

## Troubleshooting

### "Sign in to confirm you're not a bot" (YouTube)
→ Update yt-dlp: `pip install --upgrade yt-dlp`
→ Set up cookies (see Step 5 above)

### Instagram returns "Login required"
→ You need cookies.txt from a logged-in browser session

### Proxy not working
→ Verify proxy syntax in `.env`
→ For SOCKS5: ensure `pip install requests[socks]` was run
→ Test proxy separately: `curl --socks5 127.0.0.1:1080 https://api.telegram.org`

### File too large (>50MB)
→ Choose lower quality (720p or audio)
→ Or increase MAX_FILE_SIZE_MB in .env (hard limit: 50MB for bots)

### "ffmpeg not found" warning
→ Audio extraction won't work
→ Install ffmpeg: `sudo apt install ffmpeg`

---

## Project Structure

```
downloader_bot/
├── bot.py              # Main bot code
├── requirements.txt    # Python dependencies
├── .env.example        # Environment template
├── .env                # Your configuration (git-ignored)
├── cookies.txt         # Browser cookies (git-ignored)
├── bot.log             # Runtime logs
└── downloads/          # Temp download directory (auto-cleaned)
```

---

## Security Notes

- Never commit `.env` or `cookies.txt` to git
- Rotate your bot token if leaked
- Consider using a firewall to restrict access to the proxy port
- The bot deletes all downloaded files immediately after sending

---

## License

MIT — use freely, attribution appreciated.
