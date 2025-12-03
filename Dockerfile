FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    supervisor \
    x11vnc \
    xvfb \
    fluxbox \
    net-tools \
    novnc \
    ffmpeg \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install Chrome
RUN wget -q -O /tmp/google-chrome-stable_current_amd64.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get update \
    && apt-get install -y /tmp/google-chrome-stable_current_amd64.deb \
    && rm /tmp/google-chrome-stable_current_amd64.deb \
    && rm -rf /var/lib/apt/lists/*

# Install ChromeDriver - using a recent stable version
RUN CHROMEDRIVER_VERSION="131.0.6778.87" \
    && wget -q "https://storage.googleapis.com/chrome-for-testing-public/${CHROMEDRIVER_VERSION}/linux64/chromedriver-linux64.zip" -O /tmp/chromedriver.zip \
    && unzip -q /tmp/chromedriver.zip -d /tmp/ \
    && mv /tmp/chromedriver-linux64/chromedriver /usr/local/bin/chromedriver \
    && chmod +x /usr/local/bin/chromedriver \
    && rm -rf /tmp/chromedriver* \
    && echo "Chrome version:" && google-chrome --version \
    && echo "ChromeDriver version:" && chromedriver --version

# Set up working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY app/ ./app/
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Create necessary directories
RUN mkdir -p /app/downloads /app/chrome-data /app/logs

# Set up noVNC
RUN ln -s /usr/share/novnc/vnc.html /usr/share/novnc/index.html

# Expose ports
EXPOSE 5000 6080

# Set environment variables
ENV DISPLAY=:99
ENV CHROME_USER_DATA_DIR=/app/chrome-data
ENV DOWNLOAD_DIR=/app/downloads

# Start supervisor
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
