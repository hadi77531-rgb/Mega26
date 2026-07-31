#!/bin/bash
set -e

echo "=========================================="
echo "  Starting Media Downloader Bot"
echo "=========================================="

# Start PO Token server in background
echo "Starting PO Token server on port 4416..."
cd /opt/bgutil-ytdlp-pot-provider/server/node_modules
deno run --allow-env --allow-net --allow-ffi=. --allow-read=. \
    ../src/main.ts --port 4416 --host 0.0.0.0 &

PO_PID=$!
echo "PO Token server started (PID: $PO_PID)"

# Wait for PO Token server to be ready
echo "Waiting for PO Token server..."
for i in $(seq 1 30); do
    if curl -s http://127.0.0.1:4416/ping > /dev/null 2>&1; then
        echo "PO Token server is ready!"
        break
    fi
    sleep 1
done

# Set PO Token server URL for the bot
export PO_TOKEN_SERVER_URL="http://127.0.0.1:4416"

# Start the bot
echo "Starting Telegram bot..."
cd /app
python bot.py

# Cleanup
kill $PO_PID 2>/dev/null || true
