# ============================================================
#  Dockerfile for Media Downloader Bot
# ============================================================
#
#  Build:
#    docker build -t media-downloader-bot .
#
#  Run:
#    docker run -d \
#      --name media-downloader-bot \
#      --env-file .env \
#      -v $(pwd)/downloads:/app/downloads \
#      -v $(pwd)/cookies.txt:/app/cookies.txt:ro \
#      -v $(pwd)/bot.log:/app/bot.log \
#      media-downloader-bot
#
#  Logs:
#    docker logs -f media-downloader-bot
# ============================================================

FROM python:3.12-slim-bookworm

# Install ffmpeg
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY bot.py .

# Create downloads directory
RUN mkdir -p /app/downloads

# Run the bot
CMD ["python", "bot.py"]
