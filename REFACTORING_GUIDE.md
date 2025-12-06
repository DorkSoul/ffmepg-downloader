# Refactoring Guide - OOP Structure

## Overview
The application has been refactored from a single ~2000 line file into a proper Object-Oriented Programming (OOP) structure following best practices.

## New Directory Structure

```
app/
├── __init__.py
├── app.py                          # Main Flask application (application factory)
├── app_old.py                      # Backup of original monolithic file
├── config.py                       # Configuration class
├── models/                         # Data models
│   ├── __init__.py
│   └── stream_detector.py         # StreamDetector class (browser automation)
├── services/                       # Business logic services
│   ├── __init__.py
│   ├── download_service.py        # Download management (FFmpeg operations)
│   └── browser_service.py         # Browser instance management
├── utils/                          # Utility functions
│   ├── __init__.py
│   ├── playlist_parser.py         # HLS playlist parsing
│   ├── metadata_extractor.py      # FFprobe metadata extraction
│   └── thumbnail_generator.py     # Thumbnail generation from streams/files
└── routes/                         # Flask route blueprints
    ├── __init__.py
    ├── browser_routes.py           # Browser-related endpoints
    └── download_routes.py          # Download-related endpoints
```

## Key Components

### 1. Configuration (`config.py`)
- **Config class**: Manages all application configuration
  - Environment variables
  - Directory paths
  - Logging configuration
  - Startup checks

### 2. Models (`models/`)
- **StreamDetector**: Handles browser automation and stream detection
  - Chrome/Selenium management
  - CDP (Chrome DevTools Protocol) WebSocket monitoring
  - Stream detection logic
  - Resolution matching

### 3. Services (`services/`)
- **DownloadService**: Manages all download operations
  - FFmpeg download processes
  - Download queue management
  - Progress tracking
  - Thumbnail extraction from files

- **BrowserService**: Manages browser instances
  - Browser lifecycle (start/stop)
  - Chrome installation checks
  - Cookie/profile management
  - Stream selection coordination

### 4. Utils (`utils/`)
- **PlaylistParser**: HLS playlist parsing utilities
  - Fetches master playlists
  - Parses stream variants
  - Resolution matching

- **MetadataExtractor**: Stream metadata extraction
  - FFprobe integration
  - Metadata enrichment

- **ThumbnailGenerator**: Thumbnail generation
  - Stream thumbnail extraction
  - File thumbnail extraction
  - Screenshot capture

### 5. Routes (`routes/`)
- **browser_routes**: Browser-related API endpoints
  - `/api/browser/start` - Start browser
  - `/api/browser/status/<id>` - Get status
  - `/api/browser/close/<id>` - Close browser
  - `/api/browser/select-resolution` - Manual resolution selection
  - `/api/browser/select-stream` - Manual stream selection
  - `/api/browser/clear-cookies` - Clear cookies
  - `/api/browser/test/chrome` - Test Chrome installation

- **download_routes**: Download-related API endpoints
  - `/api/downloads/direct` - Direct download
  - `/api/downloads/list` - List completed downloads
  - `/api/downloads/active` - Get active downloads
  - `/api/downloads/stop/<id>` - Stop download

## Design Patterns Used

### 1. Application Factory Pattern
The `create_app()` function in `app.py` creates and configures the Flask application:
```python
def create_app():
    flask_app = Flask(__name__)
    config = Config()
    # ... initialize services, register blueprints
    return flask_app
```

### 2. Dependency Injection
Services are injected into routes during initialization:
```python
browser_bp = init_browser_routes(browser_service, download_service)
```

### 3. Separation of Concerns
- **Models**: Data and business entities
- **Services**: Business logic
- **Routes**: HTTP request/response handling
- **Utils**: Reusable utility functions
- **Config**: Configuration management

### 4. Single Responsibility Principle
Each class has a single, well-defined responsibility:
- `StreamDetector`: Stream detection
- `DownloadService`: Download management
- `BrowserService`: Browser management
- `PlaylistParser`: Playlist parsing

## Benefits of Refactoring

1. **Maintainability**: Code is organized into logical modules
2. **Testability**: Each component can be tested independently
3. **Reusability**: Utilities can be reused across the application
4. **Scalability**: Easy to add new features without touching existing code
5. **Readability**: Smaller, focused files are easier to understand
6. **Debugging**: Issues can be isolated to specific modules

## Migration Notes

The old monolithic `app.py` has been backed up as `app_old.py`. The application maintains backward compatibility - all API endpoints work exactly the same way.

### Key Changes:
1. Flask routes now use **Blueprints** for better organization
2. **Application factory pattern** for initialization
3. **Service layer** for business logic
4. **Utility modules** for reusable functions
5. **Configuration class** instead of module-level variables

## Running the Application

No changes to how you run the application:

```bash
python app/app.py
```

Or with Docker:
```bash
docker-compose up
```

## Testing

The refactored structure makes testing easier. Each component can be tested independently:

```python
# Test configuration
from app.config import Config
config = Config()

# Test services
from app.services import DownloadService
download_service = DownloadService('/path/to/downloads')

# Test utilities
from app.utils import PlaylistParser
resolutions = PlaylistParser.parse_master_playlist(content)
```

## Future Improvements

With this structure, future enhancements are easier:
1. Add unit tests for each module
2. Add database support (models already separated)
3. Add authentication/authorization middleware
4. Add API documentation (Swagger/OpenAPI)
5. Add caching layer
6. Add async/await support for better performance

## Backward Compatibility

All existing functionality is preserved:
- ✅ Browser-based stream detection
- ✅ Direct download
- ✅ Resolution selection
- ✅ Thumbnail generation
- ✅ Download management
- ✅ Cookie management
- ✅ All API endpoints

The refactoring is purely structural - the application behavior remains unchanged.
