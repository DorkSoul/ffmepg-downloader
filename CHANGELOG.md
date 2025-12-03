# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2024-12-03

### Added

#### Core Features
- **Dual Download Modes**
  - Direct download from stream URLs (.m3u8, .mpd, .mp4)
  - Browser-based detection with Chrome automation

- **Cookie Persistence**
  - Automatic session storage
  - Login once, stay logged in forever
  - Chrome user data directory persistence

- **Visual Confirmation**
  - Thumbnail capture before download completes
  - Confirmation popup with stream details
  - Auto-close countdown with manual override

- **Stream Detection**
  - Chrome DevTools Protocol network monitoring
  - HLS (.m3u8) stream detection
  - DASH (.mpd) stream detection
  - Direct MP4 detection
  - Ad/tracking URL filtering

#### User Interface
- Modern, responsive web interface
- Embedded noVNC browser viewer
- Real-time download status
- Recent downloads list
- Mobile-friendly design
- Gradient purple theme

#### Infrastructure
- Docker containerization
- Supervisor process management
- Xvfb virtual display
- x11vnc VNC server
- noVNC web VNC client
- FFmpeg video processing

#### API Endpoints
- `POST /api/download/direct` - Direct stream download
- `POST /api/browser/start` - Start browser session
- `GET /api/browser/status/:id` - Check detection status
- `POST /api/browser/close/:id` - Close browser manually
- `GET /api/downloads/list` - List completed downloads

#### Documentation
- Comprehensive README with feature overview
- Detailed installation guide (INSTALL.md)
- Quick start guide (QUICKSTART.md)
- Architecture documentation (ARCHITECTURE.txt)
- Technical reference (TECHNICAL.md)
- Deployment checklist (DEPLOYMENT-CHECKLIST.md)
- MIT License

#### Configuration
- Environment variable support
- Configurable auto-close delay
- Custom download directory
- Custom Chrome data directory
- Docker Compose for easy deployment
- Portainer-ready repository deployment

### Technical Details

#### Dependencies
- Python 3.11
- Flask 3.0.0
- Selenium 4.16.0
- Pillow 10.1.0
- FFmpeg (system)
- Google Chrome Stable
- ChromeDriver

#### Volume Mounts
- `/volume1/media/downloads` - HDD storage for videos
- `/volume2/Dockerssd/video-downloader/chrome-data` - SSD for Chrome data
- `/volume2/Dockerssd/video-downloader/logs` - SSD for logs

#### Ports
- 5000 - Flask web interface
- 6080 - noVNC web viewer

#### Security
- Local network deployment
- No default authentication
- Cookie storage in volumes
- Chrome sandbox disabled (container requirement)

### Known Limitations

- Single browser instance at a time
- DRM-protected content not supported
- Some sites may detect automation
- Linux container only
- No built-in authentication

### Credits

- Built for UGREEN NAS
- Designed to work with Portainer
- Alternative to yt-dlp/MeTube for problematic sites

---

## [Unreleased]

### Planned Features

- Multiple simultaneous browser sessions
- Download queue management
- Progress bars for active downloads
- Video format selection
- User authentication
- Download scheduling
- Webhook notifications
- Mobile app companion
- Custom FFmpeg parameters
- Database for download history

### Under Consideration

- Support for other browsers (Firefox)
- Playlist support
- Automatic retry on failure
- Bandwidth limiting
- Quality selection
- Subtitle download
- Metadata extraction

---

## Version History

| Version | Date | Description |
|---------|------|-------------|
| 1.0.0 | 2024-12-03 | Initial release with core functionality |

---

## Migration Guide

### From Version X to Y

*No migrations yet - initial release*

---

## Support

For issues, feature requests, or questions:
- Create a GitHub issue
- Check documentation in /docs
- Review TROUBLESHOOTING section in README.md

---

**Note**: This project is in active development. Breaking changes may occur before version 2.0.0.
