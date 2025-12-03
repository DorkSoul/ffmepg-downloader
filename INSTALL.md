# Installation Guide

## Prerequisites

- UGREEN NAS with Docker support
- Portainer installed (recommended) or Docker Compose CLI access
- Sufficient storage space on volumes

## Method 1: Portainer Repository Deployment (Recommended)

This is the easiest method for deploying to your UGREEN NAS.

### Step 1: Push to GitHub

```bash
# Initialize git repository (if not already done)
git init
git add .
git commit -m "Initial commit - video downloader project"

# Add your GitHub repository
git remote add origin https://github.com/yourusername/nas-video-downloader.git
git branch -M main
git push -u origin main
```

### Step 2: Deploy in Portainer

1. Open Portainer web interface on your NAS
2. Navigate to **Stacks** in the sidebar
3. Click **Add Stack** button
4. Enter stack details:
   - **Name**: `video-downloader`
   - **Build method**: Select **Repository**
   - **Repository URL**: `https://github.com/yourusername/nas-video-downloader`
   - **Repository reference**: `refs/heads/main`
   - **Compose path**: `docker-compose.yml`
5. Scroll down to **Environment variables** (optional):
   - Add any custom variables if needed
6. Click **Deploy the stack**
7. Wait for deployment to complete

### Step 3: Verify Installation

1. Check stack status in Portainer - should show "running"
2. Open http://your-nas-ip:5000 in your browser
3. You should see the Video Downloader interface

## Method 2: Docker Compose CLI

If you have SSH access to your NAS:

```bash
# Clone your repository
git clone https://github.com/yourusername/nas-video-downloader.git
cd nas-video-downloader

# Create required directories
mkdir -p /volume1/media/downloads
mkdir -p /volume2/Dockerssd/video-downloader/chrome-data
mkdir -p /volume2/Dockerssd/video-downloader/logs

# Start the container
docker-compose up -d

# Check logs
docker-compose logs -f

# Stop the container
docker-compose down
```

## Volume Setup

Before deployment, ensure these directories exist on your NAS:

```bash
# HDD storage for downloaded videos
/volume1/media/downloads

# SSD storage for Chrome data and logs
/volume2/Dockerssd/video-downloader/chrome-data
/volume2/Dockerssd/video-downloader/logs
```

### Creating Directories via SSH

```bash
# Connect to your NAS
ssh admin@your-nas-ip

# Create directories
mkdir -p /volume1/media/downloads
mkdir -p /volume2/Dockerssd/video-downloader/chrome-data
mkdir -p /volume2/Dockerssd/video-downloader/logs

# Set permissions
chmod 755 /volume1/media/downloads
chmod 755 /volume2/Dockerssd/video-downloader/chrome-data
chmod 755 /volume2/Dockerssd/video-downloader/logs
```

## Port Configuration

The application uses these ports:

- **5000**: Web interface
- **6080**: noVNC (browser view)

Ensure these ports are not used by other applications:

```bash
# Check if ports are available
netstat -tuln | grep -E ':5000|:6080'
```

If ports are in use, modify `docker-compose.yml`:

```yaml
ports:
  - "5001:5000"   # Change external port
  - "6081:6080"   # Change external port
```

## First Run

After successful deployment:

1. Access web interface: http://your-nas-ip:5000
2. Test direct download:
   - Find a sample .m3u8 URL online
   - Paste it in Direct Download mode
   - Click "Download Now"
   - Check `/volume1/media/downloads` for the file

3. Test browser mode:
   - Paste any video website URL
   - Click "Open Browser & Detect"
   - The embedded browser should appear
   - Try playing a video

## Updating

### Via Portainer

1. Go to **Stacks** > Your stack
2. Click **Editor**
3. Enable **Pull latest image**
4. Click **Update the stack**

### Via CLI

```bash
cd nas-video-downloader
git pull origin main
docker-compose down
docker-compose up -d --build
```

## Uninstallation

### Via Portainer

1. Go to **Stacks**
2. Select your stack
3. Click **Delete**
4. Optionally delete volumes:
   ```bash
   rm -rf /volume2/Dockerssd/video-downloader
   ```

### Via CLI

```bash
cd nas-video-downloader
docker-compose down
docker rmi nas-video-downloader_video-downloader

# Remove data (optional)
rm -rf /volume2/Dockerssd/video-downloader
```

## Troubleshooting Installation

### Build Fails

```bash
# Check Docker logs
docker-compose logs

# Try building manually
docker-compose build --no-cache
```

### Volume Permission Issues

```bash
# Fix permissions
sudo chown -R 1000:1000 /volume1/media/downloads
sudo chown -R 1000:1000 /volume2/Dockerssd/video-downloader
```

### Port Already in Use

```bash
# Find what's using the port
sudo netstat -tulpn | grep :5000

# Kill the process or change port in docker-compose.yml
```

### Container Won't Start

```bash
# Check container status
docker ps -a

# View full logs
docker logs nas-video-downloader

# Restart container
docker restart nas-video-downloader
```

## Support

If you encounter issues:

1. Check the logs: `docker-compose logs -f`
2. Verify all directories exist and are writable
3. Ensure ports 5000 and 6080 are available
4. Check Docker version: `docker --version` (recommend 20.10+)
5. Create a GitHub issue with error details
