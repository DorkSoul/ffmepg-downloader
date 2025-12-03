# Video Downloader Project - Technical Overview

## Project Structure

```
video-downloader/
├── app/
│   ├── app.py                 # Main Flask application
│   ├── templates/
│   │   └── index.html         # Web interface
│   └── static/                # Thumbnails stored here at runtime
├── Dockerfile                 # Container build instructions
├── docker-compose.yml         # Orchestration configuration
├── supervisord.conf           # Process manager config
├── requirements.txt           # Python dependencies
├── .env.example              # Environment variables template
├── .gitignore                # Git ignore rules
├── LICENSE                   # MIT License
├── README.md                 # Main documentation
├── INSTALL.md                # Installation guide
├── QUICKSTART.md             # Quick start guide
├── CHANGELOG.md              # Version history
└── test-setup.sh             # Setup verification script
```

## Architecture

### Components

1. **Flask Web Server** (Port 5000)
   - REST API for download operations
   - Serves web interface
   - Session management

2. **Selenium + Chrome**
   - Browser automation
   - Network traffic monitoring via Chrome DevTools Protocol
   - Cookie persistence

3. **noVNC** (Port 6080)
   - Web-based VNC client
   - Allows remote viewing of Chrome
   - Embedded in main interface

4. **FFmpeg**
   - Stream downloading
   - Thumbnail generation
   - Video format conversion

5. **Supervisor**
   - Process management
   - Keeps all services running
   - Handles service dependencies

### Data Flow

#### Direct Download Mode:
```
User Input → Flask API → FFmpeg → Downloads Directory
```

#### Browser Mode:
```
User Input → Flask API → Chrome (Selenium)
              ↓
         Network Monitor (CDP)
              ↓
         Detect Stream → FFmpeg → Downloads Directory
              ↓
         Generate Thumbnail → Show Popup
```

## Key Features Explained

### 1. Cookie Persistence

Cookies are stored in `/home/appuser/.config/google-chrome` which is mounted as a Docker volume. This means:
- Login once per site
- Subsequent visits use saved session
- Works across container restarts
- Mapped to `./chrome-data/` on host

### 2. Stream Detection

The app uses Chrome DevTools Protocol to monitor network requests:
- Captures all HTTP requests
- Filters for video MIME types
- Detects .m3u8, .mpd, .mp4, .ts files
- Prioritizes adaptive streaming formats

### 3. Visual Confirmation

When a stream is detected:
1. FFmpeg extracts a frame at 3-second mark
2. Thumbnail saved to `/app/static/thumb_{session_id}.jpg`
3. Popup displays thumbnail to user
4. Confirms correct video before full download

### 4. Countdown Timer

After download starts:
- 15-second countdown (configurable)
- User can close immediately
- User can keep open to verify
- Auto-closes when countdown ends

## Configuration Options

### Environment Variables

```bash
DOWNLOAD_PATH=/downloads        # Where videos are saved
CHROME_TIMEOUT=15              # Seconds before auto-close
DEFAULT_QUALITY=1080           # Preferred quality
DISPLAY=:99                    # X display number
```

### Port Configuration

```yaml
ports:
  - "5000:5000"  # Web interface
  - "6080:6080"  # noVNC viewer
```

Change left side to use different ports on host.

### Volume Mounts

```yaml
volumes:
  - ./downloads:/downloads                                    # Downloaded videos
  - ./chrome-data:/home/appuser/.config/google-chrome        # Chrome profile
  - /dev/shm:/dev/shm                                        # Shared memory
```

## Security Considerations

### What's Secure:
- Runs as non-root user (`appuser`)
- No exposed credentials
- Local network only by default
- Cookies stored locally

### What to Watch:
- Don't expose to internet without VPN/authentication
- Cookies contain sensitive session data
- Downloaded content may have copyright restrictions
- Browser can execute JavaScript (be careful with untrusted sites)

## Performance Optimization

### Memory Usage:
- Base: ~500MB
- Chrome running: +500-800MB
- FFmpeg downloading: +100-300MB
- **Total: ~1.5-2GB recommended**

### CPU Usage:
- Idle: Minimal
- Chrome active: Medium
- FFmpeg downloading: Medium-High (transcoding)

### Disk I/O:
- Streaming downloads are I/O intensive
- Use fast storage for better performance
- SSDs recommended for NAS deployment

## Troubleshooting Common Issues

### Chrome Won't Start
```bash
# Check shared memory
docker exec video-downloader df -h /dev/shm

# Should show 2GB
# If not, increase in docker-compose.yml:
shm_size: '4gb'
```

### Network Detection Fails
```bash
# Check Chrome DevTools Protocol
docker exec video-downloader curl http://localhost:9222/json

# Should return Chrome debugging info
```

### FFmpeg Errors
```bash
# Test FFmpeg directly
docker exec video-downloader ffmpeg -version

# Test stream download manually
docker exec video-downloader ffmpeg -i "YOUR_STREAM_URL" -t 10 test.mp4
```

### Permission Issues
```bash
# Fix download directory permissions
chmod 755 downloads chrome-data
chown -R 1000:1000 downloads chrome-data
```

## API Endpoints

### POST /api/direct-download
```json
{
  "url": "https://example.com/video.m3u8",
  "quality": "1080"
}
```
Returns: `{"session_id": "direct_1234567890"}`

### POST /api/browser-download
```json
{
  "url": "https://example.com/watch?v=12345"
}
```
Returns: `{"session_id": "browser_1234567890", "vnc_url": "..."}`

### GET /api/status/{session_id}
Returns:
```json
{
  "type": "browser",
  "url": "https://...",
  "status": "downloading",
  "filename": "video_1234567890.mp4",
  "thumbnail": "thumb_browser_1234567890.jpg",
  "stream_url": "https://..."
}
```

### POST /api/close-browser/{session_id}
Manually triggers browser close for session.

## Extending the Project

### Add Custom Headers
In `app.py`, modify FFmpeg command:
```python
cmd = [
    'ffmpeg',
    '-headers', 'User-Agent: Mozilla/5.0',
    '-i', stream_url,
    # ...
]
```

### Add Quality Detection
Enhance stream detection to parse quality from URL or manifest.

### Add Download Queue
Implement a queue system for multiple simultaneous downloads.

### Add Authentication
Add basic auth or API keys to Flask routes.

### Custom Chrome Extensions
Mount extensions directory and load in Chrome options.

## Known Limitations

1. **DRM Content**: Cannot download Widevine/PlayReady protected streams
2. **Site Detection**: Some video players use custom protocols
3. **Resource Usage**: Chrome is memory-intensive
4. **Rate Limits**: Some sites may block automated access
5. **Transcoding**: No automatic format conversion (uses `-c copy`)

## Future Enhancements

- [ ] Multi-quality selection from detected streams
- [ ] Download queue management
- [ ] Progress bars with percentage
- [ ] Automatic subtitle download
- [ ] Download history/log
- [ ] Mobile-responsive improvements
- [ ] Dark mode UI
- [ ] Webhook notifications
- [ ] Integration with media servers (Jellyfin, Plex)

## Contributing

Feel free to fork and customize! Common improvements:
- Better error messages
- Additional format support
- UI/UX enhancements
- Performance optimizations

## Support

For issues or questions:
1. Check the logs: `docker-compose logs -f`
2. Run test script: `./test-setup.sh`
3. Review INSTALL.md and README.md
4. Open GitHub issue with logs and details

---

**Built with:** Python, Flask, Selenium, FFmpeg, Docker, noVNC
**License:** MIT
**Version:** 1.0.0
