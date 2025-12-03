# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] - 2024-12-03

### Added
- Initial release
- Direct download mode for .m3u8, .mpd, and direct video URLs
- Browser mode with Chrome automation for sites requiring login
- Cookie persistence for authenticated sessions
- Visual confirmation with video thumbnail before closing browser
- Configurable countdown timer (default 15 seconds)
- noVNC integration for remote browser viewing
- FFmpeg-based video downloading
- Responsive web interface
- Docker and Docker Compose support
- Portainer compatible deployment
- Real-time download status updates

### Features
- Network stream detection (m3u8, mpd, mp4)
- Automatic quality selection
- Session management
- Error handling and user feedback
- Local network access

### Technical Details
- Python Flask backend
- Selenium WebDriver with Chrome
- FFmpeg for video processing
- Supervisor for process management
- Ubuntu 22.04 base image
