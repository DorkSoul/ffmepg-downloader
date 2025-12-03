# Installation Guide

## Prerequisites

- Docker and Docker Compose installed on your NAS
- Portainer (optional, but recommended for easier management)
- At least 2GB of available RAM
- Network access to your NAS

## Method 1: Deploy with Portainer (Recommended)

### Step 1: Clone or Download Repository

If you have Git on your NAS:
```bash
git clone https://github.com/yourusername/video-downloader.git
cd video-downloader
```

Or download and extract the ZIP file to your NAS.

### Step 2: Create Required Directories

```bash
mkdir -p downloads chrome-data
chmod 755 downloads chrome-data
```

### Step 3: Deploy via Portainer

1. Open Portainer web interface
2. Go to **Stacks** → **Add Stack**
3. Give it a name: `video-downloader`
4. Choose **Upload** and select `docker-compose.yml`
   - OR choose **Web editor** and paste the contents of `docker-compose.yml`
5. Click **Deploy the stack**

### Step 4: Access the Application

Once deployed, access the web interface at:
```
http://your-nas-ip:5000
```

The noVNC browser interface will be at:
```
http://your-nas-ip:6080
```

## Method 2: Manual Docker Compose Deployment

### Step 1: Navigate to Project Directory

```bash
cd /path/to/video-downloader
```

### Step 2: Build and Start

```bash
docker-compose up -d
```

### Step 3: Check Status

```bash
docker-compose ps
docker-compose logs -f
```

### Step 4: Stop the Service

```bash
docker-compose down
```

## Method 3: Docker Build and Run (Advanced)

### Build the Image

```bash
docker build -t video-downloader:latest .
```

### Run the Container

```bash
docker run -d \
  --name video-downloader \
  -p 5000:5000 \
  -p 6080:6080 \
  -v $(pwd)/downloads:/downloads \
  -v $(pwd)/chrome-data:/home/appuser/.config/google-chrome \
  -e DOWNLOAD_PATH=/downloads \
  -e CHROME_TIMEOUT=15 \
  -e DEFAULT_QUALITY=1080 \
  --shm-size=2gb \
  video-downloader:latest
```

## Configuration

### Environment Variables

You can customize these in `docker-compose.yml`:

- **DOWNLOAD_PATH**: Directory where videos are saved (default: `/downloads`)
- **CHROME_TIMEOUT**: Seconds to wait before closing Chrome after download starts (default: `15`)
- **DEFAULT_QUALITY**: Preferred video quality (default: `1080`)

### Port Configuration

If ports 5000 or 6080 are already in use, modify the port mappings in `docker-compose.yml`:

```yaml
ports:
  - "5001:5000"  # Change 5001 to your preferred port
  - "6081:6080"  # Change 6081 to your preferred port
```

### Volume Paths

To change where downloads are stored, modify the volumes section:

```yaml
volumes:
  - /path/to/your/downloads:/downloads
  - /path/to/chrome-data:/home/appuser/.config/google-chrome
```

## Updating

### Via Portainer

1. Go to **Stacks** → Select `video-downloader`
2. Click **Stop**
3. Update the code/configuration
4. Click **Deploy the stack** again

### Via Docker Compose

```bash
docker-compose down
git pull  # If using Git
docker-compose build
docker-compose up -d
```

## Troubleshooting

### Container won't start

Check logs:
```bash
docker-compose logs video-downloader
```

### Port conflicts

Change port mappings in `docker-compose.yml` as shown above.

### Permission issues

Ensure directories are writable:
```bash
chmod 755 downloads chrome-data
```

### Chrome crashes or won't open

Increase shared memory:
```yaml
shm_size: '4gb'  # Increase from 2gb
```

### Downloads fail

- Verify FFmpeg is working: `docker exec video-downloader ffmpeg -version`
- Check the stream URL is accessible
- Some DRM-protected content cannot be downloaded

## Uninstalling

### Via Portainer

1. Go to **Stacks** → Select `video-downloader`
2. Click **Delete**

### Via Docker Compose

```bash
docker-compose down -v  # -v removes volumes
rm -rf downloads chrome-data  # Optional: remove downloaded files
```

## Security Notes

- This service is designed for local network use only
- Do not expose ports 5000 or 6080 to the internet without proper security
- Cookies are stored locally in the `chrome-data` directory
- Only use with content you have rights to download

## Support

For issues and questions, please open an issue on the GitHub repository.
