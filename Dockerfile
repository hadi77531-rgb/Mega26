FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    unzip \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Deno v2.9+ (required by yt-dlp 2026)
# yt-dlp 2026 requires Deno >= 2.3.0 for YouTube extraction
ENV DENO_INSTALL=/root/.deno
ENV PATH="$DENO_INSTALL/bin:$PATH"
RUN curl -fsSL https://deno.land/install.sh | sh -s v2.9.2
RUN deno --version

# Clone bgutil PO Token server
RUN git clone --single-branch --branch 1.3.1 \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git \
    /opt/bgutil-ytdlp-pot-provider

# Install deno dependencies for the PO Token server
WORKDIR /opt/bgutil-ytdlp-pot-provider/server
RUN deno install --allow-scripts=npm:canvas --frozen 2>/dev/null || true

# Verify installations
RUN echo "=== Verification ===" && \
    python --version && \
    yt-dlp --version && \
    deno --version && \
    ffmpeg -version 2>&1 | head -1

# Install Python dependencies for the bot
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot code
COPY bot.py .
COPY start.sh .
RUN chmod +x start.sh

EXPOSE 8080

CMD ["./start.sh"]
