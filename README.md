# NAS Video Downloader

A Docker-based video downloader for UGREEN NAS that uses FFmpeg to download streams and videos from websites. Features an interactive browser for cookie-based authentication and automatic stream detection.

## Features

- **Direct Download**: Download videos directly from .m3u8, .mpd, or direct video URLs
- **Smart Browser Mode**: Opens a Chrome window for sites requiring login/authentication
- **Cookie Persistence**: Saves cookies so subsequent downloads work automatically
- **Visual Confirmation**: Shows video thumbnail before closing browser
- **Network Accessible**: Access from any device on your local network
- **Portainer Compatible**: Easy deployment via Docker Compose

## Quick Start

### Deploy with Portainer

1. In Portainer, go to **Stacks** → **Add Stack**
2. Name it `video-downloader`
3. Upload the `docker-compose.yml` file or paste its contents
4. Click **Deploy the stack**
5. Access the interface at `http://your-nas-ip:5000`

### Manual Docker Compose

```bash
docker-compose up -d
```

## Usage

### Direct Download Mode

1. Select "Direct Download"
2. Paste a direct video URL (e.g., .m3u8 stream URL)
3. Choose quality preference
4. Click "Download"

### Browser Mode (for sites requiring login)

1. Select "Find Link"
2. Paste the webpage URL
3. A Chrome window opens via noVNC in your browser
4. Log in if needed - cookies are saved automatically
5. Navigate to the video and play it
6. The app detects the stream and starts downloading
7. A popup shows a thumbnail for confirmation
8. Chrome closes after 15 seconds (or click to close earlier)

## Configuration

### Environment Variables

Edit these in `docker-compose.yml`:

- `DOWNLOAD_PATH`: Where videos are saved (default: `/downloads`)
- `CHROME_TIMEOUT`: Seconds before auto-closing Chrome (default: `15`)
- `DEFAULT_QUALITY`: Preferred video quality (default: `1080`)

### Volumes

- `./downloads`: Downloaded videos
- `./chrome-data`: Chrome profile (cookies, cache)
- `./app`: Application code

## Default Settings

- **Web Interface**: http://your-nas-ip:5000
- **VNC Interface**: http://your-nas-ip:6080
- **Download Location**: `./downloads`

## Requirements

- Docker and Docker Compose
- At least 2GB RAM available
- Network access to your NAS

## Troubleshooting

### Chrome window doesn't open
- Check if port 6080 is available
- Verify Chrome container is running: `docker ps`

### Downloads fail
- Check FFmpeg logs in the web interface
- Verify the stream URL is accessible
- Some DRM-protected content cannot be downloaded

### Cookies not persisting
- Ensure `./chrome-data` volume has write permissions
- Check Docker volume mounts in Portainer

## Architecture

- **Backend**: Python Flask
- **Browser**: Chrome with Remote Debugging + noVNC
- **Downloader**: FFmpeg
- **Container**: Docker with Ubuntu base

## License

MIT License - feel free to modify and use as needed!

## Contributing

This is a personal project, but suggestions and improvements are welcome via GitHub issues.
