# Technical Documentation

## Technology Stack

### Backend

- **Python 3.11**: Core application language
- **Flask 3.0**: Web framework for UI and API
- **Selenium 4.16**: Browser automation
- **FFmpeg**: Video stream downloading and processing
- **Pillow**: Image processing for thumbnails

### Frontend

- **Pure JavaScript**: No frameworks, lightweight and fast
- **CSS Grid/Flexbox**: Responsive layout
- **Fetch API**: Async communication with backend

### Infrastructure

- **Docker**: Containerization
- **Supervisor**: Process management
- **Xvfb**: Virtual display server
- **x11vnc**: VNC server
- **noVNC**: Web-based VNC client
- **Fluxbox**: Minimal window manager

## API Reference

### Direct Download

**Endpoint**: `POST /api/download/direct`

**Request Body**:
```json
{
  "url": "https://example.com/stream.m3u8",
  "filename": "my_video.mp4"  // optional
}
```

**Response**:
```json
{
  "success": true,
  "browser_id": "direct_1234567890",
  "message": "Download started",
  "output_path": "/app/downloads/my_video.mp4"
}
```

### Start Browser Session

**Endpoint**: `POST /api/browser/start`

**Request Body**:
```json
{
  "url": "https://example.com/watch/video123"
}
```

**Response**:
```json
{
  "success": true,
  "browser_id": "browser_1234567890",
  "message": "Browser started",
  "vnc_url": "/vnc"
}
```

### Check Browser Status

**Endpoint**: `GET /api/browser/status/:browser_id`

**Response**:
```json
{
  "browser_id": "browser_1234567890",
  "is_running": true,
  "download_started": true,
  "detected_streams": 1,
  "thumbnail": "base64_encoded_image_data",
  "latest_stream": {
    "url": "https://example.com/stream.m3u8",
    "type": "HLS",
    "mime_type": "application/vnd.apple.mpegurl",
    "timestamp": 1234567890.123
  },
  "download": {
    "output_path": "/app/downloads/video_1234567890.mp4",
    "stream_url": "https://example.com/stream.m3u8",
    "duration": 12.5
  }
}
```

### Close Browser

**Endpoint**: `POST /api/browser/close/:browser_id`

**Response**:
```json
{
  "success": true,
  "message": "Browser closed"
}
```

### List Downloads

**Endpoint**: `GET /api/downloads/list`

**Response**:
```json
{
  "downloads": [
    {
      "filename": "video_1234567890.mp4",
      "size": 157286400,
      "created": 1234567890.123,
      "path": "/app/downloads/video_1234567890.mp4"
    }
  ]
}
```

## Stream Detection

### Chrome DevTools Protocol

The application uses Chrome's Performance Log to capture network events:

```python
chrome_options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
```

Network events are retrieved via:
```python
logs = driver.get_log('performance')
```

### Detection Logic

Stream detection filter chain:

1. **Extension Check**: `.m3u8`, `.mpd`, `.mp4`, `.ts`, `.m4s`
2. **MIME Type Check**: `video/*`, `application/vnd.apple.mpegurl`, `application/dash+xml`
3. **Exclusion Filter**: Removes URLs containing `ad`, `doubleclick`, `analytics`, `tracking`
4. **Priority**: First valid stream triggers download

### Supported Stream Types

| Type | Format | Extension | Use Case |
|------|--------|-----------|----------|
| HLS | HTTP Live Streaming | .m3u8 | Apple/iOS, most adaptive streaming |
| DASH | Dynamic Adaptive Streaming | .mpd | YouTube, modern web video |
| MP4 | Progressive download | .mp4 | Direct video files |

## FFmpeg Command

Default FFmpeg command for stream download:

```bash
ffmpeg \
  -i <stream_url> \
  -c copy \
  -bsf:a aac_adtstoasc \
  -y \
  <output_path>
```

**Flags Explanation**:
- `-i`: Input URL
- `-c copy`: Copy streams without re-encoding (fast)
- `-bsf:a aac_adtstoasc`: Convert AAC bitstream format for MP4
- `-y`: Overwrite output file if exists

## Cookie Persistence

### Storage Location

Chrome user data directory: `/volume2/Dockerssd/video-downloader/chrome-data/`

### Structure

```
chrome-data/
├── Default/
│   ├── Cookies              # SQLite database of cookies
│   ├── Local Storage/       # localStorage data
│   ├── Session Storage/     # sessionStorage data
│   ├── IndexedDB/           # IndexedDB data
│   ├── Preferences          # Browser preferences
│   └── History              # Browsing history
└── SingletonLock           # Lock file
```

### Selenium Configuration

```python
chrome_options.add_argument(f'--user-data-dir={CHROME_USER_DATA_DIR}')
```

This ensures all browser sessions share the same profile, persisting:
- Login cookies
- Session tokens
- Local storage
- Preferences

## Threading Model

### Main Thread
- Flask request handling
- HTTP response generation

### Background Threads

1. **Network Monitor Thread** (per browser)
   - Created: When browser starts
   - Lifetime: Until browser closes
   - Function: Polls performance logs every 0.5s
   - Cleanup: Automatic on browser.close()

2. **FFmpeg Download Thread** (per download)
   - Created: When stream detected or direct download starts
   - Lifetime: Until download completes
   - Function: subprocess.Popen() for FFmpeg
   - Cleanup: Automatic on process exit

3. **Auto-Close Thread** (per browser)
   - Created: When download starts
   - Lifetime: 15 seconds (configurable)
   - Function: time.sleep() then browser.close()
   - Cancellable: Via "Keep Open" button

### Thread Safety

- `active_browsers{}`: Main thread writes, background threads read
- `download_queue{}`: Thread-safe dict operations
- Selenium driver: Single thread access per instance

## State Management

### Global State

```python
active_browsers = {}  # browser_id -> StreamDetector instance
download_queue = {}   # browser_id -> download_info dict
```

### Browser State

```python
class StreamDetector:
    browser_id: str                # Unique identifier
    driver: webdriver.Chrome       # Selenium driver instance
    detected_streams: list         # All detected stream URLs
    is_running: bool               # Browser running status
    download_started: bool         # Download triggered flag
    thumbnail_data: str            # Base64 thumbnail
```

### Download State

```python
{
    'process': subprocess.Popen,   # FFmpeg process
    'output_path': str,            # Destination file
    'stream_url': str,             # Source URL
    'started_at': float            # Unix timestamp
}
```

## Error Handling

### Browser Errors

```python
try:
    self.driver = webdriver.Chrome(...)
except WebDriverException as e:
    logger.error(f"Failed to start browser: {e}")
    return False
```

### Download Errors

```python
process = subprocess.Popen([...])
stdout, stderr = process.communicate()

if process.returncode == 0:
    logger.info(f"Download completed: {output_path}")
else:
    logger.error(f"FFmpeg error: {stderr}")
```

### Network Monitoring Errors

```python
try:
    log_data = json.loads(entry['message'])
    # Process log entry
except json.JSONDecodeError:
    continue  # Skip malformed entries
except Exception as e:
    logger.error(f"Error processing log entry: {e}")
```

## Performance Considerations

### Memory Usage

- **Chrome**: ~200-500 MB per instance
- **Xvfb**: ~50 MB
- **Flask**: ~50 MB
- **FFmpeg**: Minimal (streaming to disk)
- **Total**: ~500-800 MB baseline + 200-500 MB per active browser

### Disk I/O

- **Chrome data (SSD)**: Random access, frequent small writes
- **Downloads (HDD)**: Sequential writes, large files
- **Logs (SSD)**: Append-only, small frequent writes

### Network Bandwidth

- Single stream download: Typically 1-10 Mbps
- Multiple simultaneous downloads: Sum of all streams
- Browser traffic: Minimal (pages load once)

### CPU Usage

- FFmpeg: 10-30% during download (copy mode)
- Chrome: 10-50% during video playback
- Python: <5% (mostly idle waiting for I/O)

## Configuration Options

### Environment Variables

```bash
# Download location
DOWNLOAD_DIR=/app/downloads

# Chrome profile location
CHROME_USER_DATA_DIR=/app/chrome-data

# Auto-close delay (seconds)
AUTO_CLOSE_DELAY=15

# Flask environment
FLASK_ENV=production

# Display server
DISPLAY=:99
```

### Docker Resources

```yaml
shm_size: 2gb                    # Shared memory for Chrome
security_opt:
  - seccomp:unconfined          # Chrome sandbox requirement
```

## Development

### Local Testing

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export DISPLAY=:99
export DOWNLOAD_DIR=./downloads
export CHROME_USER_DATA_DIR=./chrome-data

# Run Flask
python -m app.app
```

### Debugging

```python
# Enable Flask debug mode
app.run(host='0.0.0.0', port=5000, debug=True)

# Increase logging
logging.basicConfig(level=logging.DEBUG)

# Selenium debugging
chrome_options.add_argument('--enable-logging')
chrome_options.add_argument('--v=1')
```

### Testing Stream Detection

```python
# Test URL filtering
def test_is_video_stream():
    detector = StreamDetector('test')

    assert detector._is_video_stream('https://example.com/video.m3u8', '')
    assert detector._is_video_stream('https://example.com/manifest.mpd', '')
    assert not detector._is_video_stream('https://ads.example.com/video.m3u8', '')
```

## Limitations

### Known Issues

1. **Protected Streams**: DRM-protected content cannot be downloaded
2. **Rate Limiting**: Some sites may detect automated access
3. **Dynamic Streams**: Some streams expire or require tokens
4. **Concurrent Browsers**: Single browser instance at a time (by design)

### Browser Compatibility

- Chrome only (Chromium-based)
- Requires CDP support
- Selenium 4.x required

### Platform Support

- Linux only (Docker container)
- Requires X11 for Chrome
- FFmpeg must be available

## Security Best Practices

1. **Network Isolation**: Do not expose to public internet
2. **Volume Permissions**: Restrict access to chrome-data
3. **Rate Limiting**: Add request throttling if needed
4. **Input Validation**: URLs are not sanitized beyond basic checks
5. **Cookie Protection**: Encrypt volume if storing sensitive tokens

## Monitoring

### Log Files

```bash
# Application logs
/app/logs/flask.log
/app/logs/flask_error.log

# Browser logs
/app/logs/xvfb.log
/app/logs/fluxbox.log
/app/logs/x11vnc.log
/app/logs/novnc.log

# Supervisor
/app/logs/supervisord.log
```

### Health Checks

```bash
# Check if all processes running
docker exec nas-video-downloader supervisorctl status

# Check Flask
curl http://localhost:5000/

# Check noVNC
curl http://localhost:6080/vnc.html

# Check downloads
ls -lh /volume1/media/downloads/
```

### Resource Monitoring

```bash
# Container stats
docker stats nas-video-downloader

# Disk usage
du -sh /volume1/media/downloads
du -sh /volume2/Dockerssd/video-downloader
```
