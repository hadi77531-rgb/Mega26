FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    unzip \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Deno v2.9+ (required by yt-dlp 2026)
ENV DENO_INSTALL=/root/.deno
ENV PATH="$DENO_INSTALL/bin:$PATH"
RUN curl -fsSL https://deno.land/install.sh | sh -s v2.9.2

# Clone bgutil PO Token server
RUN git clone --single-branch --branch 1.3.1 \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git \
    /opt/bgutil-ytdlp-pot-provider

# Install deno dependencies for the PO Token server
WORKDIR /opt/bgutil-ytdlp-pot-provider/server
RUN deno install --allow-scripts=npm:canvas --frozen 2>/dev/null || true

# Install Python dependencies FIRST (includes yt-dlp)
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# NOW verify everything is installed
RUN echo "=== Verification ===" && \
    python --version && \
    yt-dlp --version && \
    deno --version && \
    ffmpeg -version 2>&1 | head -1

# Copy bot code
COPY bot.py .
COPY start.sh .
RUN chmod +x start.sh

EXPOSE 8080

CMD ["./start.sh"]
