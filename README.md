# NAS Video Downloader

A self-hosted video downloader designed for UGREEN NAS that downloads videos and streams using FFmpeg with browser-based authentication support.

## Features

- **Dual Download Modes**
  - Direct Download: Download from known stream URLs (.m3u8, .mpd, .mp4)
  - Browser Mode: Automated stream detection with Chrome browser

- **Cookie Persistence** - Log in once, stay logged in forever
- **Visual Confirmation** - See thumbnail before download completes
- **Stream Detection** - Automatically detects HLS, DASH, and MP4 streams
- **Network Accessible** - Access from any device on your network
- **Modern Web Interface** - Clean, responsive design

## Quick Start

### Deploy with Portainer

1. In Portainer, go to **Stacks** > **Add Stack**
2. Choose **Repository** deployment method
3. Enter your GitHub repository URL
4. Set the compose path: `docker-compose.yml`
5. Click **Deploy the stack**

### Manual Docker Compose

```bash
# Clone the repository
git clone <your-repo-url>
cd ffmepg-downloader

# Start the container
docker-compose up -d

# Check logs
docker-compose logs -f
```

## Access

- **Web Interface**: http://your-nas-ip:5000
- **noVNC Browser**: http://your-nas-ip:6080 (embedded in interface)

## Usage

### Direct Download Mode

1. Open the web interface
2. Paste a direct stream URL (e.g., `https://example.com/stream.m3u8`)
3. Optionally enter a custom filename
4. Click "Download Now"

### Browser Mode (Find Link)

**First time on a new site:**

1. Select "Find Link" mode
2. Paste the webpage URL (e.g., `https://videosite.com/watch/12345`)
3. Click "Open Browser & Detect"
4. Chrome window appears - log in to the site
5. Navigate to the video and play it
6. Download starts automatically when stream is detected
7. Popup shows thumbnail and confirms download
8. Browser closes after 15 seconds

**Next time on the same site:**

1. Paste a new video URL from the same site
2. Click "Open Browser & Detect"
3. You're already logged in (cookies saved!)
4. Video plays automatically
5. Download starts immediately

## Volume Mapping

The docker-compose.yml maps:

- `/volume1/media/downloads` - Downloaded videos (HDD)
- `/volume2/Dockerssd/video-downloader/chrome-data` - Chrome cookies & session (SSD)
- `/volume2/Dockerssd/video-downloader/logs` - Application logs (SSD)

## Configuration

Environment variables in `docker-compose.yml`:

- `AUTO_CLOSE_DELAY` - Seconds before auto-closing browser (default: 15)
- `DOWNLOAD_DIR` - Where to save videos
- `CHROME_USER_DATA_DIR` - Chrome profile location

## Troubleshooting

### Browser doesn't open
- Check that port 6080 is not blocked
- Verify Chrome installed: `docker exec -it nas-video-downloader google-chrome --version`

### Stream not detected
- Ensure video is actually playing in the browser
- Some sites use protected streams that can't be detected
- Check logs: `docker-compose logs -f`

### Downloads not appearing
- Verify volume mount exists: `/volume1/media/downloads`
- Check container logs for FFmpeg errors
- Ensure sufficient disk space

### Cookie persistence not working
- Check `/volume2/Dockerssd/video-downloader/chrome-data` exists and is writable
- Don't use incognito/private mode in the browser view

## Architecture

- **Flask** - Web server and API
- **Selenium** - Chrome automation
- **Chrome DevTools Protocol** - Network traffic monitoring
- **FFmpeg** - Video downloading
- **noVNC** - Browser embedding
- **Xvfb** - Virtual display
- **Supervisor** - Process management

## Security Notes

- This tool is designed for **personal use on a local network**
- Do not expose ports to the internet without proper authentication
- Respect copyright laws and terms of service
- Only download content you have rights to

## Support

For issues, please create a GitHub issue with:
- Error messages from logs
- Steps to reproduce
- Browser/OS information

## License

MIT License - See LICENSE file for details
