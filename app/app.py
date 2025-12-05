import os
import sys
import time
import subprocess
import threading
import json
import logging
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException
from PIL import Image
import io
import base64
import websocket
import requests as req_lib

# Configure logging to stdout/stderr for Docker logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/app/logs/flask.log')
    ]
)
logger = logging.getLogger(__name__)

# Silence noisy third-party loggers
logging.getLogger('selenium').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('websocket').setLevel(logging.WARNING)

# Log startup information
logger.info("=" * 80)
logger.info("NAS VIDEO DOWNLOADER STARTING")
logger.info("=" * 80)
logger.info(f"Python version: {sys.version}")
logger.info(f"Working directory: {os.getcwd()}")
logger.info(f"DISPLAY: {os.getenv('DISPLAY')}")
logger.info(f"Download dir: {os.getenv('DOWNLOAD_DIR')}")
logger.info(f"Chrome data dir: {os.getenv('CHROME_USER_DATA_DIR')}")

app = Flask(__name__)

# Configuration
DOWNLOAD_DIR = os.getenv('DOWNLOAD_DIR', '/app/downloads')
CHROME_USER_DATA_DIR = os.getenv('CHROME_USER_DATA_DIR', '/app/chrome-data')
AUTO_CLOSE_DELAY = int(os.getenv('AUTO_CLOSE_DELAY', '15'))

# Check Chrome and ChromeDriver at startup
def check_chrome_installation():
    logger.info("Checking Chrome installation...")
    try:
        # Check Chrome
        chrome_result = subprocess.run(['google-chrome', '--version'],
                                      capture_output=True, text=True, timeout=5)
        logger.info(f"Chrome: {chrome_result.stdout.strip()}")

        # Check ChromeDriver
        driver_result = subprocess.run(['chromedriver', '--version'],
                                      capture_output=True, text=True, timeout=5)
        logger.info(f"ChromeDriver: {driver_result.stdout.strip()}")

        # Check Display
        display = os.getenv('DISPLAY', 'NOT SET')
        logger.info(f"DISPLAY environment: {display}")

        # Check Xvfb
        xvfb_result = subprocess.run(['ps', 'aux'],
                                    capture_output=True, text=True, timeout=5)
        if 'Xvfb' in xvfb_result.stdout:
            logger.info("Xvfb is running ✓")
        else:
            logger.warning("Xvfb not found in process list!")

        # Check directories
        logger.info(f"Download dir exists: {os.path.exists(DOWNLOAD_DIR)}")
        logger.info(f"Chrome data dir exists: {os.path.exists(CHROME_USER_DATA_DIR)}")

        return True
    except Exception as e:
        logger.error(f"Chrome installation check failed: {e}")
        return False

check_chrome_installation()

# Global state
active_browsers = {}
download_queue = {}

# Utility functions for resolution parsing
def fetch_master_playlist(url):
    """Fetch and return master playlist content"""
    try:
        import requests
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.text
        return None
    except Exception as e:
        logger.error(f"Failed to fetch master playlist: {e}")
        return None

def extract_stream_metadata_with_ffprobe(stream_url, timeout=8):
    """Extract metadata from stream using ffprobe as fallback"""
    try:
        logger.info(f"Extracting metadata with ffprobe for: {stream_url[:100]}...")

        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_streams',
            '-show_format',
            stream_url
        ]

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            text=True
        )

        if result.returncode == 0 and result.stdout:
            import json
            data = json.loads(result.stdout)

            metadata = {
                'resolution': '',
                'framerate': '',
                'codecs': ''
            }

            # Find video stream
            video_stream = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'), None)
            if video_stream:
                # Extract resolution
                width = video_stream.get('width')
                height = video_stream.get('height')
                if width and height:
                    metadata['resolution'] = f"{width}x{height}"

                # Extract framerate
                fps_str = video_stream.get('r_frame_rate', '')
                if fps_str and '/' in fps_str:
                    try:
                        num, denom = fps_str.split('/')
                        fps = float(num) / float(denom)
                        metadata['framerate'] = f"{fps:.3f}"
                    except:
                        pass

                # Extract codec
                codec_name = video_stream.get('codec_name', '')
                if codec_name:
                    metadata['codecs'] = codec_name

            logger.info(f"Extracted metadata: {metadata}")
            return metadata
        else:
            logger.warning(f"ffprobe failed: {result.stderr}")
            return None

    except subprocess.TimeoutExpired:
        logger.warning(f"ffprobe timed out after {timeout}s")
        return None
    except Exception as e:
        logger.error(f"Failed to extract metadata with ffprobe: {e}")
        return None

def parse_master_playlist(content):
    """Parse master playlist and extract resolution information"""
    resolutions = []
    lines = content.split('\n')

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Look for stream info lines
        if line.startswith('#EXT-X-STREAM-INF:'):
            # Parse attributes
            attrs = {}
            for attr in line.split(','):
                if '=' in attr:
                    key, value = attr.split('=', 1)
                    attrs[key.strip()] = value.strip('"')

            # Get the URL from next line
            if i + 1 < len(lines):
                stream_url = lines[i + 1].strip()

                if stream_url and not stream_url.startswith('#'):
                    # Get base name and framerate
                    base_name = attrs.get('IVS-NAME', attrs.get('STABLE-VARIANT-ID', ''))
                    framerate = attrs.get('FRAME-RATE', '')

                    # Normalize name to always include framerate
                    if framerate and base_name:
                        # Extract numeric framerate (e.g., "60.000" -> "60")
                        fps_numeric = framerate.split('.')[0] if '.' in str(framerate) else str(framerate)
                        # Only append if not already at the end (e.g., "1080p60" already has 60)
                        # Check for pattern like "720p60" or "1080p30" (ends with fps number)
                        import re
                        if not re.search(r'p\d+$', base_name):  # If doesn't end with 'p' followed by digits
                            base_name = f"{base_name}{fps_numeric}"

                    resolution_info = {
                        'url': stream_url,
                        'bandwidth': int(attrs.get('BANDWIDTH', 0)),
                        'resolution': attrs.get('RESOLUTION', ''),
                        'framerate': framerate,
                        'codecs': attrs.get('CODECS', ''),
                        'name': base_name
                    }

                    resolutions.append(resolution_info)

        i += 1

    # Sort by bandwidth (highest first)
    resolutions.sort(key=lambda x: x['bandwidth'], reverse=True)

    # Log sorted resolutions for debugging
    logger.info(f"Parsed {len(resolutions)} resolutions, sorted by bandwidth:")
    for idx, res in enumerate(resolutions):
        logger.info(f"  [{idx}] {res['name']} - {res['resolution']} @ {res.get('framerate', '?')}fps - Bandwidth: {res['bandwidth']}")

    return resolutions

def enrich_stream_metadata(stream_dict):
    """Enrich stream metadata using ffprobe if HLS attributes are missing"""
    needs_enrichment = (
        not stream_dict.get('resolution') or
        not stream_dict.get('framerate') or
        not stream_dict.get('codecs')
    )

    if needs_enrichment:
        missing_fields = []
        if not stream_dict.get('resolution'):
            missing_fields.append('resolution')
        if not stream_dict.get('framerate'):
            missing_fields.append('framerate')
        if not stream_dict.get('codecs'):
            missing_fields.append('codecs')

        logger.info(f"Stream metadata incomplete (missing: {', '.join(missing_fields)}), attempting to enrich with ffprobe: {stream_dict.get('name', 'unknown')}")
        metadata = extract_stream_metadata_with_ffprobe(stream_dict['url'])

        if metadata:
            enriched = []
            # Fill in missing fields
            if not stream_dict.get('resolution') and metadata.get('resolution'):
                stream_dict['resolution'] = metadata['resolution']
                enriched.append(f"resolution={metadata['resolution']}")

            if not stream_dict.get('framerate') and metadata.get('framerate'):
                stream_dict['framerate'] = metadata['framerate']
                enriched.append(f"framerate={metadata['framerate']}")

            if not stream_dict.get('codecs') and metadata.get('codecs'):
                stream_dict['codecs'] = metadata['codecs']
                enriched.append(f"codecs={metadata['codecs']}")

            if enriched:
                logger.info(f"  ✓ Enriched with: {', '.join(enriched)}")
            else:
                logger.warning("  → ffprobe ran but couldn't extract any missing metadata")
        else:
            logger.warning("  → ffprobe enrichment failed, metadata will remain incomplete")
    else:
        logger.debug(f"Stream metadata already complete for: {stream_dict.get('name', 'unknown')}")

    return stream_dict

def match_resolution(resolutions, preferred):
    """Find best matching resolution"""
    if not resolutions:
        return None

    preferred_lower = preferred.lower()

    # Try exact match first
    for res in resolutions:
        if res['name'].lower() == preferred_lower:
            logger.info(f"Found exact match for {preferred}: {res['name']}")
            return res

    # Try partial match (e.g., "1080p" matches "1080p60")
    for res in resolutions:
        if preferred_lower in res['name'].lower():
            logger.info(f"Found partial match for {preferred}: {res['name']}")
            return res

    # Special case: "source" means highest quality
    if preferred_lower == 'source':
        logger.info(f"Source requested, returning highest quality: {resolutions[0]['name']}")
        return resolutions[0]

    logger.warning(f"No match found for {preferred}")
    return None

class StreamDetector:
    def __init__(self, browser_id, resolution='1080p', framerate='any', auto_download=False):
        self.browser_id = browser_id
        self.driver = None
        self.detected_streams = []
        self.is_running = False
        self.download_started = False
        self.thumbnail_data = None
        self.resolution = resolution
        self.framerate = framerate  # 'any', '60', '30'
        self.auto_download = auto_download
        self.awaiting_resolution_selection = False
        self.available_resolutions = []
        self.selected_stream_url = None
        # WebSocket CDP connection
        self.ws = None
        self.ws_url = None
        self.cdp_session_id = 1

    def start_browser(self, url):
        """Start Chrome with DevTools Protocol enabled"""
        max_retries = 2
        retry_count = 0

        while retry_count < max_retries:
            try:
                logger.info(f"Starting Chrome browser for {url}")

                chrome_options = Options()
                # Essential flags for Docker
                chrome_options.add_argument('--no-sandbox')
                chrome_options.add_argument('--disable-setuid-sandbox')
                chrome_options.add_argument('--disable-dev-shm-usage')

                # Enable remote debugging for CDP WebSocket (port 0 = auto-assign)
                chrome_options.add_argument('--remote-debugging-port=0')
                # Allow WebSocket connections to CDP from any origin
                chrome_options.add_argument('--remote-allow-origins=*')

                # GPU and rendering
                chrome_options.add_argument('--disable-gpu')
                chrome_options.add_argument('--disable-software-rasterizer')

                # Optimization flags
                chrome_options.add_argument('--disable-extensions')
                chrome_options.add_argument('--disable-background-networking')
                chrome_options.add_argument('--disable-sync')
                chrome_options.add_argument('--disable-translate')
                chrome_options.add_argument('--disable-default-apps')
                chrome_options.add_argument('--disable-notifications')

                # User data directory for cookie persistence
                chrome_options.add_argument(f'--user-data-dir={CHROME_USER_DATA_DIR}')

                # Logging
                chrome_options.add_argument('--enable-logging')
                chrome_options.add_argument('--v=1')

                chrome_options.add_experimental_option('w3c', True)
                chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])

                # Enable performance logging to capture network events
                chrome_options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

                logger.info("Initializing ChromeDriver service")
                service = Service(
                    '/usr/local/bin/chromedriver',
                    log_output='/app/logs/chromedriver.log'
                )

                logger.info("Creating Chrome webdriver instance...")
                logger.debug(f"Chrome options: {[arg for arg in chrome_options.arguments]}")

                try:
                    self.driver = webdriver.Chrome(service=service, options=chrome_options)
                    logger.info("Chrome webdriver created successfully!")
                except Exception as driver_error:
                    logger.error(f"Failed to create Chrome webdriver: {driver_error}")

                    # If this is the first attempt and error mentions "Chrome instance exited"
                    if retry_count == 0 and "Chrome instance exited" in str(driver_error):
                        logger.warning("Chrome failed to start with user-data-dir, cleaning lock files and retrying...")
                        retry_count += 1

                        # Clean up problematic lock files in user-data-dir (DO NOT kill other browser sessions)
                        try:
                            import glob
                            lock_files = glob.glob(os.path.join(CHROME_USER_DATA_DIR, '**/SingletonLock'), recursive=True)
                            lock_files.extend(glob.glob(os.path.join(CHROME_USER_DATA_DIR, '**/lockfile'), recursive=True))

                            for lock_file in lock_files:
                                try:
                                    os.remove(lock_file)
                                    logger.info(f"Removed lock file: {lock_file}")
                                except Exception as remove_error:
                                    logger.warning(f"Could not remove {lock_file}: {remove_error}")
                        except Exception as cleanup_error:
                            logger.warning(f"Error during lock file cleanup: {cleanup_error}")

                        # Small delay to let file system catch up
                        time.sleep(1)
                        continue  # Retry
                    else:
                        # Try to get more details
                        try:
                            chromedriver_output = subprocess.run(
                                ['chromedriver', '--version'],
                                capture_output=True, text=True, timeout=5
                            )
                            logger.error(f"ChromeDriver test: {chromedriver_output.stdout}")
                            logger.error(f"ChromeDriver stderr: {chromedriver_output.stderr}")
                        except Exception as e2:
                            logger.error(f"Could not test ChromeDriver: {e2}")
                        raise

                self.driver.set_window_size(1920, 1080)
                break  # Success, exit retry loop

            except WebDriverException as e:
                logger.error(f"WebDriver error starting browser: {e}")
                if retry_count < max_retries - 1:
                    retry_count += 1
                    logger.info(f"Retrying... attempt {retry_count + 1}/{max_retries}")
                    time.sleep(2)
                    continue
                logger.error(f"Error details: {str(e)}")
                return False
            except Exception as e:
                logger.error(f"Unexpected error starting browser: {type(e).__name__}: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                return False

        if retry_count >= max_retries:
            logger.error("Failed to start Chrome after all retry attempts")
            return False

        # Get CDP WebSocket URL for real-time event monitoring
        try:
            logger.info("Getting Chrome DevTools Protocol WebSocket URL...")

            # Get the debugger address from Chrome
            debugger_address = None
            if 'goog:chromeOptions' in self.driver.capabilities:
                debugger_address = self.driver.capabilities['goog:chromeOptions'].get('debuggerAddress')

            if debugger_address:
                logger.info(f"Chrome debugger address: {debugger_address}")
                # Query the debugger to get WebSocket URL
                debugger_url = f"http://{debugger_address}/json"
                try:
                    response = req_lib.get(debugger_url, timeout=5)
                    if response.status_code == 200:
                        pages = response.json()
                        if pages and len(pages) > 0:
                            # Get the first page's WebSocket URL
                            self.ws_url = pages[0].get('webSocketDebuggerUrl')
                            logger.info(f"✓ Got CDP WebSocket URL: {self.ws_url[:80]}...")
                        else:
                            logger.warning("No pages found in CDP debugger response")
                    else:
                        logger.warning(f"CDP debugger returned status {response.status_code}")
                except Exception as e:
                    logger.warning(f"Could not query CDP debugger: {e}")
            else:
                logger.warning("No debugger address in Chrome capabilities")

            # Also enable Network domain via execute_cdp_cmd as backup
            logger.info("Enabling Network domain via execute_cdp_cmd...")
            self.driver.execute_cdp_cmd('Network.enable', {})
            logger.info("Network domain enabled via execute_cdp_cmd")

        except Exception as e:
            logger.warning(f"Could not set up CDP: {e}")

        # Start WebSocket CDP listener BEFORE navigating to catch initial requests
        if self.ws_url:
            threading.Thread(target=self._cdp_websocket_listener, daemon=True).start()
            # Give WebSocket a moment to connect
            time.sleep(0.5)
        else:
            logger.warning("No WebSocket URL available, falling back to polling only")

        # Start monitoring network traffic (legacy polling as backup)
        threading.Thread(target=self._monitor_network, daemon=True).start()

        logger.info(f"Loading {url}...")
        self.driver.get(url)
        self.is_running = True
        return True

    def _cdp_websocket_listener(self):
        """Real-time CDP WebSocket listener"""

        def on_message(ws, message):
            """Handle incoming CDP messages - capture ALL network activity like DevTools"""
            try:
                data = json.loads(message)
                method = data.get('method', '')
                params = data.get('params', {})

                # Log ALL Network events (not filtered)
                if method.startswith('Network.'):
                    # Extract URL from various event types
                    url = None
                    mime_type = ''

                    if method == 'Network.requestWillBeSent':
                        request = params.get('request', {})
                        url = request.get('url', '')
                        request_method = request.get('method', '')
                        request_id = params.get('requestId', '')

                        # Log ALL requests containing m3u8
                        if 'm3u8' in url.lower():
                            logger.info(f"[CDP-WS] 🔍 REQUEST (m3u8): {request_method} {url}")
                            logger.info(f"[CDP-WS]   └─ RequestID: {request_id}")
                            logger.info(f"[CDP-WS]   └─ Headers: {request.get('headers', {})}")

                    elif method == 'Network.responseReceived':
                        response = params.get('response', {})
                        url = response.get('url', '')
                        mime_type = response.get('mimeType', '')
                        status = response.get('status', '')
                        request_id = params.get('requestId', '')

                        # Log ALL responses containing m3u8 OR mpegurl MIME type
                        if 'm3u8' in url.lower() or 'mpegurl' in mime_type.lower():
                            logger.info(f"[CDP-WS] 🎯 RESPONSE (m3u8): Status={status} | MIME={mime_type}")
                            logger.info(f"[CDP-WS]   └─ URL: {url}")
                            logger.info(f"[CDP-WS]   └─ RequestID: {request_id}")
                            logger.info(f"[CDP-WS]   └─ Headers: {response.get('headers', {})}")

                            # Process this as a detected stream
                            if self._is_video_stream(url, mime_type):
                                stream_info = {
                                    'url': url,
                                    'type': self._get_stream_type(url),
                                    'mime_type': mime_type,
                                    'timestamp': time.time()
                                }

                                if stream_info not in self.detected_streams:
                                    logger.info(f"[CDP-WS] ✓✓✓ DETECTED STREAM: type={stream_info['type']}")
                                    self.detected_streams.append(stream_info)

                                    # Start download for the first valid stream
                                    if not self.download_started and not self.awaiting_resolution_selection:
                                        logger.info(f"[CDP-WS] Processing detected stream...")
                                        self._handle_stream_detection(stream_info)

                    elif method == 'Network.dataReceived':
                        request_id = params.get('requestId', '')
                        data_length = params.get('dataLength', 0)
                        # Only log if we care about this request (has m3u8)
                        # We'll rely on requestId correlation from earlier logs

                    elif method == 'Network.loadingFinished':
                        request_id = params.get('requestId', '')
                        # Could log completion of m3u8 requests here

                    elif method == 'Network.loadingFailed':
                        request_id = params.get('requestId', '')
                        error_text = params.get('errorText', '')
                        logger.warning(f"[CDP-WS] ⚠️ Loading failed: RequestID={request_id}, Error={error_text}")

                # Handle Fetch events (modern video players use fetch/XHR)
                elif method == 'Fetch.requestPaused':
                    request = params.get('request', {})
                    url = request.get('url', '')
                    request_id = params.get('requestId', '')

                    # Check for m3u8 playlists
                    if 'm3u8' in url.lower():
                        # Check if this is likely a master playlist (not a media playlist)
                        # Common patterns:
                        # - Twitch: usher.ttvnw.net (master) vs *.playlist.ttvnw.net (media)
                        # - Generic: /master.m3u8 vs /chunklist_*.m3u8
                        is_likely_master = (
                            'usher' in url.lower() or           # Twitch master playlists
                            'master' in url.lower() or          # Common master playlist naming
                            '/playlist.m3u8' in url.lower() or  # Generic master naming
                            '/index.m3u8' in url.lower() or     # Generic index
                            'api' in url.lower()                # API endpoints often serve master playlists
                        )

                        # Exclude obvious media playlists
                        is_likely_media = (
                            '/chunklist' in url.lower() or
                            '/media_' in url.lower() or
                            '/segment' in url.lower()
                        )

                        # Only process master playlists
                        if not is_likely_media and (is_likely_master or not self.detected_streams):
                            logger.info(f"Detected master playlist: {url[:100]}...")

                            # Process this as a detected stream
                            mime_type = 'application/vnd.apple.mpegurl'
                            if self._is_video_stream(url, mime_type):
                                stream_info = {
                                    'url': url,
                                    'type': 'HLS',
                                    'mime_type': mime_type,
                                    'timestamp': time.time()
                                }

                                if stream_info not in self.detected_streams:
                                    self.detected_streams.append(stream_info)

                                    # Start download for the first valid stream
                                    if not self.download_started and not self.awaiting_resolution_selection:
                                        self._handle_stream_detection(stream_info)

                    # Continue the request (don't block it)
                    try:
                        continue_cmd = {
                            "id": self.cdp_session_id,
                            "method": "Fetch.continueRequest",
                            "params": {"requestId": request_id}
                        }
                        self.cdp_session_id += 1
                        ws.send(json.dumps(continue_cmd))
                    except Exception as e:
                        logger.error(f"[CDP-WS] Error continuing fetch request: {e}")

            except json.JSONDecodeError as e:
                logger.error(f"[CDP-WS] JSON decode error: {e}")
            except Exception as e:
                logger.error(f"[CDP-WS] Error processing message: {e}")

        def on_error(ws, error):
            logger.error(f"[CDP-WS] WebSocket error: {error}")

        def on_close(ws, close_status_code, close_msg):
            pass  # WebSocket closed - no need to log for normal operation

        def on_open(ws):
            # Enable all CDP domains that DevTools uses to capture network activity
            try:
                # Network domain - CRITICAL for capturing network requests
                enable_cmd = {
                    "id": self.cdp_session_id,
                    "method": "Network.enable",
                    "params": {
                        "maxTotalBufferSize": 100000000,
                        "maxResourceBufferSize": 50000000,
                        "maxPostDataSize": 50000000
                    }
                }
                self.cdp_session_id += 1
                ws.send(json.dumps(enable_cmd))

                # Page domain - catches page lifecycle events
                page_enable_cmd = {
                    "id": self.cdp_session_id,
                    "method": "Page.enable",
                    "params": {}
                }
                self.cdp_session_id += 1
                ws.send(json.dumps(page_enable_cmd))

                # Fetch domain - catches fetch/XHR requests (used by modern video players)
                fetch_enable_cmd = {
                    "id": self.cdp_session_id,
                    "method": "Fetch.enable",
                    "params": {
                        "patterns": [{"urlPattern": "*", "requestStage": "Request"}]
                    }
                }
                self.cdp_session_id += 1
                ws.send(json.dumps(fetch_enable_cmd))

                # Runtime domain - catches console messages and JS execution
                runtime_enable_cmd = {
                    "id": self.cdp_session_id,
                    "method": "Runtime.enable",
                    "params": {}
                }
                self.cdp_session_id += 1
                ws.send(json.dumps(runtime_enable_cmd))

                logger.info("Network monitoring started")

            except Exception as e:
                logger.error(f"[CDP-WS] Error sending enable commands: {e}")

        try:
            # Create WebSocket connection
            self.ws = websocket.WebSocketApp(
                self.ws_url,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
                on_open=on_open
            )

            # Run forever (blocking call in this thread)
            self.ws.run_forever()

        except Exception as e:
            logger.error(f"[CDP-WS] Fatal error in WebSocket listener: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def _monitor_network(self):
        """Monitor network traffic for video streams (legacy backup)"""
        loop_count = 0

        while self.is_running and self.driver:
            try:
                logs = self.driver.get_log('performance')
                loop_count += 1

                # Log every 2 minutes (240 loops × 0.5s) to show we're alive
                if loop_count % 240 == 0:
                    logger.info(f"[LEGACY-POLL] Loop #{loop_count}, monitoring active")

                for entry in logs:
                    try:
                        log_data = json.loads(entry['message'])
                        message = log_data.get('message', {})
                        method = message.get('method', '')

                        # DEBUG: Check for responseReceivedExtraInfo which has content-type
                        if method == 'Network.responseReceivedExtraInfo':
                            params = message.get('params', {})
                            headers = params.get('headers', {})
                            content_type = headers.get('content-type', '')
                            request_id = params.get('requestId', '')

                            if 'mpegurl' in content_type.lower() or 'm3u8' in content_type.lower():
                                logger.info(f"[EXTRA_INFO] Found HLS content-type! RequestID: {request_id}, Content-Type: {content_type}")

                        # Check Network.responseReceived events (legacy polling backup)
                        if method == 'Network.responseReceived':
                            params = message.get('params', {})
                            response = params.get('response', {})
                            url = response.get('url', '')
                            mime_type = response.get('mimeType', '')
                            request_id = params.get('requestId', '')

                            # Only log .m3u8 files (reduce noise)
                            if '.m3u8' in url.lower() or 'mpegurl' in mime_type.lower():
                                logger.info(f"[LEGACY-POLL] 🔍 Found .m3u8: {url[:200]}... | MIME: {mime_type}")

                            # DEBUG: Log all video-related URLs being checked
                            if any(ext in url.lower() for ext in ['.mpd', '.mp4', '.ts', '.m4s', 'ttvnw']):
                                logger.debug(f"Checking potential video URL: {url[:150]}... (mime: {mime_type})")

                            # Detect video streams
                            if self._is_video_stream(url, mime_type):
                                stream_info = {
                                    'url': url,
                                    'type': self._get_stream_type(url),
                                    'mime_type': mime_type,
                                    'timestamp': time.time()
                                }

                                if stream_info not in self.detected_streams:
                                    logger.info(f"✓ DETECTED STREAM: type={stream_info['type']}, url={url[:100]}...")
                                    self.detected_streams.append(stream_info)

                                    # Start download for the first valid stream
                                    if not self.download_started and not self.awaiting_resolution_selection:
                                        logger.info(f"Processing first detected stream...")
                                        self._handle_stream_detection(stream_info)

                    except json.JSONDecodeError:
                        continue
                    except Exception as e:
                        logger.error(f"Error processing log entry: {e}")

                time.sleep(0.5)

            except Exception as e:
                logger.error(f"Error in network monitoring: {e}")
                break

    def _is_video_stream(self, url, mime_type):
        """Check if URL is a video stream - ONLY playlists, not segments"""
        # ONLY accept playlist files (.m3u8, .mpd), NOT individual segments (.ts, .m4s)
        playlist_extensions = ['.m3u8', '.mpd']
        playlist_mime_types = ['application/vnd.apple.mpegurl', 'application/dash+xml',
                               'application/x-mpegurl', 'vnd.apple.mpegurl']

        # Filter out individual segment files (.ts, .m4s, individual .mp4)
        if url.lower().endswith('.ts') or url.lower().endswith('.m4s') or '/segment/' in url.lower():
            logger.debug(f"Rejected (segment file): {url[:80]}...")
            return False

        # HIGH PRIORITY: Twitch HLS API endpoint (usher.ttvnw.net)
        if 'usher.ttvnw.net' in url.lower() and '.m3u8' in url.lower():
            logger.info(f"✓✓✓ TWITCH HLS API DETECTED: {url[:150]}...")
            return True

        # Check for playlist extensions
        if any(url.lower().endswith(ext) or f'{ext}?' in url.lower() for ext in playlist_extensions):
            # Filter out ads and tracking
            if any(keyword in url.lower() for keyword in ['doubleclick', 'analytics', 'tracking']):
                logger.debug(f"Rejected (ads/tracking): {url[:80]}...")
                return False
            logger.info(f"✓ Accepted (playlist): {url[:120]}...")
            return True

        # Check for playlist in path (e.g., /playlist/, /master.m3u8)
        if 'playlist' in url.lower() and '.m3u8' in url.lower():
            logger.info(f"✓ Accepted (playlist path): {url[:120]}...")
            return True

        # Check MIME type for playlists
        if any(mime in mime_type.lower() for mime in playlist_mime_types):
            logger.info(f"✓ Accepted (playlist MIME {mime_type}): {url[:120]}...")
            return True

        return False

    def _get_stream_type(self, url):
        """Determine stream type from URL"""
        if '.m3u8' in url.lower():
            return 'HLS'
        elif '.mpd' in url.lower():
            return 'DASH'
        elif '.mp4' in url.lower():
            return 'MP4'
        else:
            return 'UNKNOWN'

    def _match_stream(self, resolutions):
        """Find best matching stream based on resolution and framerate preferences"""
        if not resolutions:
            return None

        logger.info(f"Matching stream - Resolution: {self.resolution}, Framerate: {self.framerate}")

        # Extract target resolution (e.g., "1080" from "1080p")
        target_res = self.resolution.lower().replace('p', '')

        # Special case: "source" means highest quality
        if target_res == 'source':
            logger.info("Source requested, returning highest quality stream")
            return resolutions[0]  # Already sorted by bandwidth (highest first)

        # Filter by resolution first
        matching_res = []
        for res in resolutions:
            res_str = res.get('resolution', '').lower()
            res_name = res.get('name', '').lower()

            # Check if resolution matches (e.g., "1920x1080" contains "1080")
            if target_res in res_str or target_res in res_name:
                matching_res.append(res)

        if not matching_res:
            logger.warning(f"No streams found matching resolution {self.resolution}, using highest quality")
            return resolutions[0]

        logger.info(f"Found {len(matching_res)} streams matching resolution {self.resolution}")

        # Now filter by framerate
        if self.framerate == 'any':
            # Return highest bandwidth (already sorted)
            logger.info(f"Framerate='any', selecting highest bandwidth: {matching_res[0].get('name')}")
            return matching_res[0]

        elif self.framerate == '60':
            # Only accept 60fps - NO FALLBACK
            fps_60 = [r for r in matching_res if '60' in str(r.get('framerate', ''))]
            if fps_60:
                logger.info("Found 60fps stream")
                return fps_60[0]
            # Return None if specific framerate not found
            logger.warning(f"No 60fps stream found for {self.resolution}, showing all streams for manual selection")
            return None

        elif self.framerate == '30':
            # Only accept 30fps - NO FALLBACK
            fps_30 = [r for r in matching_res if '30' in str(r.get('framerate', ''))]
            if fps_30:
                logger.info("Found 30fps stream")
                return fps_30[0]
            # Return None if specific framerate not found
            logger.warning(f"No 30fps stream found for {self.resolution}, showing all streams for manual selection")
            return None

        # Default: return highest bandwidth of matching resolution
        return matching_res[0]

    def _handle_stream_detection(self, stream_info):
        """Handle detected stream - check if it's a master playlist"""
        stream_url = stream_info['url']

        # Check if this is an HLS stream
        if '.m3u8' in stream_url.lower():
            logger.info(f"Detected .m3u8 stream, checking if it's a master playlist...")

            # Fetch and check if it's a master playlist
            content = fetch_master_playlist(stream_url)

            if content and '#EXT-X-STREAM-INF:' in content:
                logger.info("This is a master playlist! Parsing resolutions...")

                # Parse available resolutions
                resolutions = parse_master_playlist(content)

                if resolutions:
                    logger.info(f"Found {len(resolutions)} resolutions")

                    # Check if auto-download is enabled
                    if self.auto_download:
                        logger.info("Auto-download enabled, finding matching stream...")
                        matched_stream = self._match_stream(resolutions)

                        if matched_stream:
                            logger.info(f"Matched stream: {matched_stream['name']} - {matched_stream['resolution']} @ {matched_stream['framerate']}fps")
                            # Start download immediately
                            self._start_download_with_stream(matched_stream)
                        else:
                            logger.warning("No matching stream found, showing all streams for manual selection")
                            self.awaiting_resolution_selection = True
                            self.available_resolutions = resolutions

                            # Enrich metadata and generate thumbnails in background (same as manual mode)
                            for res in resolutions[:5]:
                                threading.Thread(
                                    target=self._enrich_and_add_thumbnail,
                                    args=(res,),
                                    daemon=True
                                ).start()
                    else:
                        # Manual mode: show all streams for user to choose
                        logger.info("Manual mode, showing all available streams")
                        self.awaiting_resolution_selection = True
                        self.available_resolutions = resolutions

                        # Enrich metadata and generate thumbnails in background (non-blocking)
                        # Limit to first 5 streams to avoid overload
                        for res in resolutions[:5]:
                            threading.Thread(
                                target=self._enrich_and_add_thumbnail,
                                args=(res,),
                                daemon=True
                            ).start()
                else:
                    # Couldn't parse resolutions, show single stream
                    logger.warning("Could not parse resolutions from master playlist")
                    self.awaiting_resolution_selection = True
                    stream_entry = {
                        'url': stream_url,
                        'bandwidth': 0,
                        'resolution': '',
                        'framerate': '',
                        'codecs': '',
                        'name': 'Master Playlist (unparsed)'
                    }
                    self.available_resolutions = [stream_entry]
                    # Enrich and add thumbnail in background
                    threading.Thread(
                        target=self._enrich_and_add_thumbnail,
                        args=(stream_entry,),
                        daemon=True
                    ).start()
            else:
                # Not a master playlist, show as single stream or auto-download
                logger.info("Not a master playlist, treating as single stream")
                if self.auto_download:
                    logger.info("Auto-download enabled, downloading single stream")
                    self._start_download_with_url(stream_url, stream_info['type'])
                else:
                    logger.info("Manual mode, showing single stream for selection")
                    self.awaiting_resolution_selection = True
                    stream_entry = {
                        'url': stream_url,
                        'bandwidth': 0,
                        'resolution': '',
                        'framerate': '',
                        'codecs': '',
                        'name': stream_info['type']
                    }
                    self.available_resolutions = [stream_entry]
                    # Enrich and add thumbnail in background
                    threading.Thread(
                        target=self._enrich_and_add_thumbnail,
                        args=(stream_entry,),
                        daemon=True
                    ).start()
        else:
            # Not HLS, show as single stream or auto-download
            logger.info("Not HLS stream, treating as single stream")
            if self.auto_download:
                logger.info("Auto-download enabled, downloading stream")
                self._start_download_with_url(stream_url, stream_info['type'])
            else:
                logger.info("Manual mode, showing stream for selection")
                self.awaiting_resolution_selection = True
                stream_entry = {
                    'url': stream_url,
                    'bandwidth': 0,
                    'resolution': '',
                    'framerate': '',
                    'codecs': '',
                    'name': stream_info['type']
                }
                self.available_resolutions = [stream_entry]
                # Enrich and add thumbnail in background
                threading.Thread(
                    target=self._enrich_and_add_thumbnail,
                    args=(stream_entry,),
                    daemon=True
                ).start()

    def _start_download(self, stream_info):
        """Start downloading the detected stream"""
        self._start_download_with_url(stream_info['url'], stream_info['type'])

    def _start_download_with_stream(self, stream):
        """Start download with stream object (contains all metadata)"""
        # Use the normalized name from the stream (already includes framerate from parse_master_playlist)
        resolution_name = stream.get('name', 'video')
        self._start_download_with_url(stream['url'], resolution_name, stream)

    def _start_download_with_url(self, stream_url, resolution_name, stream_metadata=None):
        """Start download with specific URL and resolution name"""
        self.download_started = True
        self.selected_stream_url = stream_url
        self.selected_stream_metadata = stream_metadata  # Store for download popup

        logger.info(f"Starting download for resolution: {resolution_name}")
        logger.info(f"Stream URL: {stream_url}")
        if stream_metadata:
            logger.info(f"Stream metadata: name={stream_metadata.get('name')}, res={stream_metadata.get('resolution')}, fps={stream_metadata.get('framerate')}")

            # Reuse existing thumbnail if available
            if 'thumbnail' in stream_metadata and stream_metadata['thumbnail']:
                # Extract base64 data (remove data:image/jpeg;base64, prefix if present)
                thumbnail = stream_metadata['thumbnail']
                if thumbnail.startswith('data:image/'):
                    self.thumbnail_data = thumbnail.split(',', 1)[1]
                else:
                    self.thumbnail_data = thumbnail
                logger.info("Reusing existing thumbnail from stream metadata")
        else:
            logger.warning("No stream metadata available for download popup")

        # Start download process in background thread to avoid blocking driver operations
        threading.Thread(
            target=self._process_download,
            args=(stream_url, resolution_name),
            daemon=True
        ).start()

    def _process_download(self, stream_url, resolution_name):
        """Process download in background thread"""
        # Wait a moment for video to start playing
        logger.info("Waiting 3 seconds for video to load...")
        time.sleep(3)

        # Capture thumbnail only if not already available from stream metadata
        if not self.thumbnail_data:
            logger.info("No existing thumbnail, capturing from browser...")
            self._capture_thumbnail()
        else:
            logger.info("Using existing thumbnail from stream metadata")

        # Generate filename
        timestamp = int(time.time())
        filename = f"video_{resolution_name}_{timestamp}.mp4"
        output_path = os.path.join(DOWNLOAD_DIR, filename)

        # Start FFmpeg download in background
        threading.Thread(
            target=self._download_with_ffmpeg,
            args=(stream_url, output_path),
            daemon=True
        ).start()

        # DEBUG MODE: Auto-close disabled for debugging
        # threading.Thread(
        #     target=self._auto_close_browser,
        #     daemon=True
        # ).start()

    def _capture_thumbnail(self):
        """Capture screenshot of current video"""
        try:
            if self.driver:
                screenshot = self.driver.get_screenshot_as_png()
                image = Image.open(io.BytesIO(screenshot))

                # Resize to thumbnail
                image.thumbnail((400, 300))

                # Convert to base64
                buffered = io.BytesIO()
                image.save(buffered, format="PNG")
                self.thumbnail_data = base64.b64encode(buffered.getvalue()).decode('utf-8')

                logger.info("Thumbnail captured successfully")
        except Exception as e:
            logger.error(f"Failed to capture thumbnail: {e}")

    def _generate_stream_thumbnail(self, stream_url):
        """Extract a single frame from a stream URL for thumbnail"""
        temp_file = None
        try:
            logger.info(f"Generating thumbnail for stream: {stream_url[:100]}...")

            # Create temporary output file
            temp_file = f"/tmp/thumb_{int(time.time())}_{os.getpid()}.jpg"

            # Use ffmpeg to extract a frame at 2 seconds into the stream
            # Added -loglevel error to reduce noise, increased timeout to 15s
            cmd = [
                'ffmpeg',
                '-loglevel', 'error',
                '-i', stream_url,
                '-ss', '00:00:02',  # Seek to 2 seconds
                '-vframes', '1',     # Extract 1 frame
                '-q:v', '2',         # High quality JPEG
                '-y',                # Overwrite
                temp_file
            ]

            logger.debug(f"Running ffmpeg command: {' '.join(cmd[:5])}...")

            # Run with timeout (15 seconds max - increased from 10)
            process = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15
            )

            # Check if thumbnail was created
            if os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
                # Read and encode as base64
                with open(temp_file, 'rb') as f:
                    thumbnail_data = base64.b64encode(f.read()).decode('utf-8')

                # Clean up temp file
                os.remove(temp_file)

                logger.info(f"✓ Thumbnail generated successfully ({len(thumbnail_data)} bytes)")
                return f"data:image/jpeg;base64,{thumbnail_data}"
            else:
                if os.path.exists(temp_file):
                    logger.warning(f"Thumbnail file created but empty (size: {os.path.getsize(temp_file)})")
                else:
                    logger.warning("Thumbnail file was not created by ffmpeg")

                if process.stderr:
                    stderr_text = process.stderr.decode('utf-8', errors='ignore')
                    if stderr_text.strip():
                        logger.warning(f"FFmpeg stderr: {stderr_text[:200]}")

                return None

        except subprocess.TimeoutExpired:
            logger.warning("Thumbnail generation timed out after 15 seconds")
            return None
        except Exception as e:
            logger.error(f"Failed to generate thumbnail: {type(e).__name__}: {e}")
            import traceback
            logger.debug(f"Thumbnail generation traceback: {traceback.format_exc()}")
            return None
        finally:
            # Clean up temp file if it exists
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                    logger.debug(f"Cleaned up temp thumbnail file: {temp_file}")
                except Exception as cleanup_error:
                    logger.debug(f"Failed to clean up temp file: {cleanup_error}")

    def _add_thumbnail_to_stream(self, stream_dict):
        """Generate and add thumbnail to a stream dictionary"""
        try:
            stream_url = stream_dict.get('url')
            if stream_url:
                thumbnail = self._generate_stream_thumbnail(stream_url)
                if thumbnail:
                    stream_dict['thumbnail'] = thumbnail
                    logger.info(f"Added thumbnail to stream: {stream_dict.get('name', 'unknown')}")
        except Exception as e:
            logger.error(f"Error adding thumbnail to stream: {e}")

    def _enrich_and_add_thumbnail(self, stream_dict):
        """Enrich stream metadata and add thumbnail (combined operation for manual selection)"""
        try:
            # First, enrich metadata if needed
            enrich_stream_metadata(stream_dict)

            # Then add thumbnail
            self._add_thumbnail_to_stream(stream_dict)
        except Exception as e:
            logger.error(f"Error enriching stream data: {e}")

    def _download_with_ffmpeg(self, stream_url, output_path):
        """Download stream using FFmpeg"""
        try:
            logger.info(f"Starting FFmpeg download: {stream_url} -> {output_path}")

            cmd = [
                'ffmpeg',
                '-i', stream_url,
                '-c', 'copy',
                '-bsf:a', 'aac_adtstoasc',
                '-y',  # Overwrite output file
                output_path
            ]

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )

            # Store process info with metadata
            # Get stream metadata for display
            if hasattr(self, 'selected_stream_metadata') and self.selected_stream_metadata:
                metadata = self.selected_stream_metadata
                resolution_display = metadata.get('resolution') or metadata.get('name', 'Unknown')
                # If resolution is like "1920x1080" and we have framerate, combine them
                if metadata.get('resolution') and 'x' in str(metadata.get('resolution')):
                    fps = metadata.get('framerate', '').split('.')[0] if metadata.get('framerate') else ''
                    resolution_display = f"{metadata.get('resolution')}@{fps}fps" if fps else metadata.get('resolution')
                elif metadata.get('name'):
                    resolution_display = metadata.get('name')
            else:
                resolution_display = 'Unknown'
                metadata = {}

            download_queue[self.browser_id] = {
                'process': process,
                'output_path': output_path,
                'stream_url': stream_url,
                'started_at': time.time(),
                'resolution_name': resolution_display,
                'resolution': metadata.get('resolution', 'Unknown'),
                'framerate': metadata.get('framerate', 'Unknown'),
                'codecs': metadata.get('codecs', 'Unknown'),
                'filename': os.path.basename(output_path)
            }

            # Wait for download to complete
            stdout, stderr = process.communicate()

            if process.returncode == 0:
                logger.info(f"Download completed: {output_path}")
            else:
                logger.error(f"FFmpeg error: {stderr}")

        except Exception as e:
            logger.error(f"Download failed: {e}")

    def _auto_close_browser(self):
        """Auto-close browser after delay"""
        time.sleep(AUTO_CLOSE_DELAY)
        if self.is_running:
            logger.info(f"Auto-closing browser {self.browser_id}")
            self.close()

    def close(self):
        """Close the browser"""
        self.is_running = False

        # Close WebSocket connection
        if self.ws:
            try:
                logger.info(f"[CDP-WS] Closing WebSocket connection...")
                self.ws.close()
            except Exception as e:
                logger.error(f"[CDP-WS] Error closing WebSocket: {e}")

        if self.driver:
            try:
                self.driver.quit()
                logger.info(f"Browser {self.browser_id} closed")
            except Exception as e:
                logger.error(f"Error closing browser: {e}")

        # Clean up
        if self.browser_id in active_browsers:
            del active_browsers[self.browser_id]

    def get_status(self):
        """Get current status"""
        status = {
            'browser_id': self.browser_id,
            'is_running': self.is_running,
            'download_started': self.download_started,
            'detected_streams': len(self.detected_streams),
            'thumbnail': self.thumbnail_data,
            'latest_stream': self.detected_streams[-1] if self.detected_streams else None,
            'awaiting_resolution_selection': self.awaiting_resolution_selection,
            'available_resolutions': self.available_resolutions,
            'selected_stream_metadata': getattr(self, 'selected_stream_metadata', None)
        }

        return status


@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')


@app.route('/api/download/direct', methods=['POST'])
def download_direct():
    """Direct download from stream URL"""
    try:
        data = request.json
        stream_url = data.get('url')

        if not stream_url:
            return jsonify({'error': 'No URL provided'}), 400

        # Generate filename
        timestamp = int(time.time())
        filename = data.get('filename', f"video_{timestamp}.mp4")
        output_path = os.path.join(DOWNLOAD_DIR, filename)

        # Start download in background
        browser_id = f"direct_{timestamp}"
        threading.Thread(
            target=_direct_download,
            args=(browser_id, stream_url, output_path),
            daemon=True
        ).start()

        return jsonify({
            'success': True,
            'browser_id': browser_id,
            'message': 'Download started',
            'output_path': output_path
        })

    except Exception as e:
        logger.error(f"Direct download error: {e}")
        return jsonify({'error': str(e)}), 500


def _direct_download(browser_id, stream_url, output_path):
    """Execute direct download"""
    try:
        cmd = [
            'ffmpeg',
            '-i', stream_url,
            '-c', 'copy',
            '-bsf:a', 'aac_adtstoasc',
            '-y',
            output_path
        ]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )

        download_queue[browser_id] = {
            'process': process,
            'output_path': output_path,
            'stream_url': stream_url,
            'started_at': time.time()
        }

        stdout, stderr = process.communicate()

        if process.returncode == 0:
            logger.info(f"Direct download completed: {output_path}")
        else:
            logger.error(f"Direct download failed: {stderr}")

    except Exception as e:
        logger.error(f"Direct download error: {e}")


@app.route('/api/browser/start', methods=['POST'])
def start_browser():
    """Start browser for stream detection"""
    try:
        data = request.json
        url = data.get('url')
        resolution = data.get('resolution', '1080p')
        framerate = data.get('framerate', 'any')  # 'any', '60', '30'
        auto_download = data.get('auto_download', False)

        if not url:
            return jsonify({'error': 'No URL provided'}), 400

        logger.info(f"Starting browser with resolution: {resolution}, framerate: {framerate}, auto_download: {auto_download}")

        # Generate browser ID
        browser_id = f"browser_{int(time.time())}"

        # Create and start detector with new parameters
        detector = StreamDetector(browser_id, resolution, framerate, auto_download)
        active_browsers[browser_id] = detector

        if detector.start_browser(url):
            return jsonify({
                'success': True,
                'browser_id': browser_id,
                'message': 'Browser started',
                'vnc_url': f'/vnc'
            })
        else:
            return jsonify({'error': 'Failed to start browser'}), 500

    except Exception as e:
        logger.error(f"Browser start error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/browser/status/<browser_id>', methods=['GET'])
def browser_status(browser_id):
    """Get browser status"""
    try:
        if browser_id in active_browsers:
            detector = active_browsers[browser_id]
            status = detector.get_status()

            # Add download info if available
            if browser_id in download_queue:
                download_info = download_queue[browser_id]
                status['download'] = {
                    'output_path': download_info['output_path'],
                    'stream_url': download_info['stream_url'],
                    'duration': time.time() - download_info['started_at']
                }

            return jsonify(status)
        else:
            return jsonify({'error': 'Browser not found'}), 404

    except Exception as e:
        logger.error(f"Status check error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/browser/close/<browser_id>', methods=['POST'])
def close_browser(browser_id):
    """Close browser manually"""
    try:
        if browser_id in active_browsers:
            detector = active_browsers[browser_id]
            detector.close()
            return jsonify({'success': True, 'message': 'Browser closed'})
        else:
            return jsonify({'error': 'Browser not found'}), 404

    except Exception as e:
        logger.error(f"Browser close error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/browser/select-resolution', methods=['POST'])
def select_resolution():
    """User manually selected a resolution"""
    try:
        data = request.json
        browser_id = data.get('browser_id')
        stream = data.get('stream')

        if not all([browser_id, stream]):
            return jsonify({'error': 'Missing required parameters'}), 400

        if browser_id not in active_browsers:
            return jsonify({'error': 'Browser not found'}), 404

        detector = active_browsers[browser_id]

        logger.info(f"User selected resolution: {stream.get('name')}")
        logger.info(f"Stream URL: {stream.get('url')}")
        logger.info(f"Stream object received from frontend (before enrichment): {stream}")

        # IMPORTANT: Enrich the stream metadata synchronously before downloading
        # The stream from frontend may have incomplete metadata because enrichment
        # happens asynchronously in background threads
        logger.info("Enriching selected stream metadata before download...")
        enrich_stream_metadata(stream)
        logger.info(f"Stream object after enrichment: {stream}")

        # Clear awaiting state
        detector.awaiting_resolution_selection = False

        # Start download with selected stream (will normalize filename with framerate)
        detector._start_download_with_stream(stream)

        return jsonify({
            'success': True,
            'message': f'Starting download for {stream.get("name")}'
        })

    except Exception as e:
        logger.error(f"Resolution selection error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/browser/select-stream', methods=['POST'])
def select_stream():
    """User manually selected a stream from the modal"""
    try:
        data = request.json
        browser_id = data.get('browser_id')
        stream_url = data.get('stream_url')

        if not browser_id or not stream_url:
            return jsonify({'error': 'Missing required parameters'}), 400

        if browser_id not in active_browsers:
            return jsonify({'error': 'Browser not found'}), 404

        detector = active_browsers[browser_id]

        logger.info(f"User selected stream from modal")
        logger.info(f"Stream URL: {stream_url}")

        # Find the full stream object from available resolutions
        selected_stream = None
        for res in detector.available_resolutions:
            if res['url'] == stream_url:
                selected_stream = res
                break

        if not selected_stream:
            # Fallback if not found in available_resolutions
            logger.warning("Stream not found in available_resolutions, creating minimal stream object")
            selected_stream = {
                'url': stream_url,
                'name': 'selected_stream',
                'resolution': '',
                'framerate': '',
                'codecs': ''
            }

        stream_name = selected_stream.get('name', 'selected_stream')
        logger.info(f"Selected stream: {stream_name}")
        logger.info(f"Stream object before enrichment: {selected_stream}")

        # IMPORTANT: Enrich the stream metadata synchronously before downloading
        logger.info("Enriching selected stream metadata before download...")
        enrich_stream_metadata(selected_stream)
        logger.info(f"Stream object after enrichment: {selected_stream}")

        # Clear awaiting state
        detector.awaiting_resolution_selection = False

        # Start download with selected stream and metadata
        detector._start_download_with_url(stream_url, stream_name, selected_stream)

        return jsonify({
            'success': True,
            'message': f'Starting download for {stream_name}'
        })

    except Exception as e:
        logger.error(f"Stream selection error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/clear-cookies', methods=['POST'])
def clear_cookies():
    """Clear Chrome cookies and profile data"""
    try:
        logger.info("Clear cookies requested")

        # Close all active browser sessions first
        browsers_to_close = list(active_browsers.keys())
        for browser_id in browsers_to_close:
            try:
                detector = active_browsers[browser_id]
                detector.close()
                logger.info(f"Closed browser {browser_id}")
            except Exception as e:
                logger.error(f"Error closing browser {browser_id}: {e}")

        # Force kill any remaining Chrome/ChromeDriver processes
        try:
            logger.info("Force killing Chrome and ChromeDriver processes...")
            subprocess.run(['pkill', '-9', 'chrome'], check=False, timeout=5)
            subprocess.run(['pkill', '-9', 'chromedriver'], check=False, timeout=5)
            logger.info("Process kill commands executed")
        except Exception as e:
            logger.warning(f"Error killing processes: {e}")

        # Wait for processes to die and file handles to release
        logger.info("Waiting for processes to terminate...")
        time.sleep(3)

        # Delete Chrome user data directory contents
        if os.path.exists(CHROME_USER_DATA_DIR):
            try:
                logger.info(f"Clearing Chrome data directory: {CHROME_USER_DATA_DIR}")
                import shutil

                # Instead of removing the directory itself (which is a Docker volume mount),
                # remove all contents inside it
                cleared_count = 0
                failed_count = 0

                for item in os.listdir(CHROME_USER_DATA_DIR):
                    item_path = os.path.join(CHROME_USER_DATA_DIR, item)
                    try:
                        if os.path.isfile(item_path) or os.path.islink(item_path):
                            os.unlink(item_path)
                            cleared_count += 1
                            logger.debug(f"Removed file: {item}")
                        elif os.path.isdir(item_path):
                            # Try to remove directory, ignore if busy
                            try:
                                shutil.rmtree(item_path)
                                cleared_count += 1
                                logger.debug(f"Removed directory: {item}")
                            except OSError as dir_error:
                                # If directory is locked, try to remove its contents
                                logger.warning(f"Cannot remove {item}, trying to clear contents: {dir_error}")
                                try:
                                    for root, dirs, files in os.walk(item_path, topdown=False):
                                        for name in files:
                                            try:
                                                os.remove(os.path.join(root, name))
                                            except:
                                                pass
                                        for name in dirs:
                                            try:
                                                os.rmdir(os.path.join(root, name))
                                            except:
                                                pass
                                    cleared_count += 1
                                except Exception as walk_error:
                                    logger.error(f"Failed to clear contents of {item}: {walk_error}")
                                    failed_count += 1
                    except Exception as item_error:
                        logger.error(f"Failed to remove {item}: {item_error}")
                        failed_count += 1

                logger.info(f"Chrome data cleared: {cleared_count} items removed, {failed_count} items failed")

                if cleared_count > 0 or failed_count == 0:
                    return jsonify({
                        'success': True,
                        'message': f'Cookies cleared: {cleared_count} items removed' +
                                  (f', {failed_count} items could not be removed (may be in use)' if failed_count > 0 else '')
                    })
                else:
                    return jsonify({
                        'success': False,
                        'error': 'Could not clear any Chrome data - files may be locked'
                    }), 500

            except Exception as e:
                logger.error(f"Error clearing Chrome data: {e}")
                import traceback
                logger.error(traceback.format_exc())
                return jsonify({
                    'success': False,
                    'error': f'Failed to clear Chrome data: {str(e)}'
                }), 500
        else:
            logger.warning(f"Chrome data directory does not exist: {CHROME_USER_DATA_DIR}")
            # Create it anyway
            os.makedirs(CHROME_USER_DATA_DIR, exist_ok=True)
            return jsonify({
                'success': True,
                'message': 'Chrome data directory created (was not present)'
            })

    except Exception as e:
        logger.error(f"Clear cookies error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@app.route('/api/downloads/list', methods=['GET'])
def list_downloads():
    """List all downloads"""
    try:
        downloads = []

        # List completed downloads
        if os.path.exists(DOWNLOAD_DIR):
            for filename in os.listdir(DOWNLOAD_DIR):
                filepath = os.path.join(DOWNLOAD_DIR, filename)
                if os.path.isfile(filepath):
                    stat = os.stat(filepath)
                    downloads.append({
                        'filename': filename,
                        'size': stat.st_size,
                        'created': stat.st_ctime,
                        'path': filepath
                    })

        # Sort by creation time (newest first)
        downloads.sort(key=lambda x: x['created'], reverse=True)

        return jsonify({'downloads': downloads})

    except Exception as e:
        logger.error(f"List downloads error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/downloads/active', methods=['GET'])
def active_downloads():
    """Get active downloads with progress"""
    try:
        active = []

        for browser_id, download_info in list(download_queue.items()):
            process = download_info.get('process')
            output_path = download_info.get('output_path')
            started_at = download_info.get('started_at')

            # Check if file exists and get size
            file_size = 0
            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path)

            # Calculate duration
            duration = int(time.time() - started_at)

            # Check if process is still running
            is_running = process.poll() is None if process else False

            active.append({
                'browser_id': browser_id,
                'filename': download_info.get('filename', 'Unknown'),
                'resolution': download_info.get('resolution_name', 'Unknown'),
                'resolution_detail': download_info.get('resolution', 'Unknown'),
                'framerate': download_info.get('framerate', 'Unknown'),
                'codecs': download_info.get('codecs', 'Unknown'),
                'size': file_size,
                'duration': duration,
                'is_running': is_running
            })

        return jsonify({'active_downloads': active})

    except Exception as e:
        logger.error(f"Active downloads error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/downloads/stop/<browser_id>', methods=['POST'])
def stop_download(browser_id):
    """Stop an active download"""
    try:
        if browser_id in download_queue:
            download_info = download_queue[browser_id]
            process = download_info.get('process')

            if process and process.poll() is None:
                logger.info(f"Stopping download for browser {browser_id}")
                process.terminate()
                process.wait(timeout=5)
                logger.info(f"Download stopped for browser {browser_id}")

            del download_queue[browser_id]

            return jsonify({'success': True, 'message': 'Download stopped'})
        else:
            return jsonify({'error': 'Download not found'}), 404

    except Exception as e:
        logger.error(f"Stop download error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/test/chrome', methods=['GET'])
def test_chrome():
    """Test endpoint to diagnose Chrome issues"""
    try:
        logger.info("=" * 80)
        logger.info("CHROME TEST ENDPOINT CALLED")
        logger.info("=" * 80)

        results = {}

        # Test 1: Check Chrome binary
        try:
            chrome_result = subprocess.run(['google-chrome', '--version'],
                                          capture_output=True, text=True, timeout=5)
            results['chrome_version'] = chrome_result.stdout.strip()
            results['chrome_available'] = True
            logger.info(f"✓ Chrome available: {results['chrome_version']}")
        except Exception as e:
            results['chrome_available'] = False
            results['chrome_error'] = str(e)
            logger.error(f"✗ Chrome not available: {e}")

        # Test 2: Check ChromeDriver
        try:
            driver_result = subprocess.run(['chromedriver', '--version'],
                                          capture_output=True, text=True, timeout=5)
            results['chromedriver_version'] = driver_result.stdout.strip()
            results['chromedriver_available'] = True
            logger.info(f"✓ ChromeDriver available: {results['chromedriver_version']}")
        except Exception as e:
            results['chromedriver_available'] = False
            results['chromedriver_error'] = str(e)
            logger.error(f"✗ ChromeDriver not available: {e}")

        # Test 3: Check DISPLAY
        display = os.getenv('DISPLAY')
        results['display'] = display
        logger.info(f"DISPLAY={display}")

        # Test 4: Try running Chrome binary directly
        try:
            logger.info("Testing Chrome binary directly...")
            chrome_direct = subprocess.run(
                ['google-chrome', '--no-sandbox', '--headless', '--disable-gpu', '--dump-dom', 'about:blank'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if chrome_direct.returncode == 0:
                logger.info("✓ Chrome binary runs successfully!")
                results['chrome_direct_test'] = 'SUCCESS'
            else:
                logger.error(f"✗ Chrome binary failed with exit code {chrome_direct.returncode}")
                logger.error(f"Chrome stdout: {chrome_direct.stdout[:500]}")
                logger.error(f"Chrome stderr: {chrome_direct.stderr[:500]}")
                results['chrome_direct_test'] = 'FAILED'
                results['chrome_direct_stdout'] = chrome_direct.stdout[:500]
                results['chrome_direct_stderr'] = chrome_direct.stderr[:500]
        except subprocess.TimeoutExpired:
            logger.error("✗ Chrome binary timed out")
            results['chrome_direct_test'] = 'TIMEOUT'
        except Exception as e:
            logger.error(f"✗ Chrome binary test error: {e}")
            results['chrome_direct_test'] = 'ERROR'
            results['chrome_direct_error'] = str(e)

        # Test 5: Check ldd on Chrome binary
        try:
            logger.info("Checking Chrome library dependencies...")
            ldd_result = subprocess.run(
                ['ldd', '/opt/google/chrome/chrome'],
                capture_output=True,
                text=True,
                timeout=5
            )
            missing_libs = [line for line in ldd_result.stdout.split('\n') if 'not found' in line]
            if missing_libs:
                logger.error(f"✗ Missing libraries: {missing_libs}")
                results['missing_libraries'] = missing_libs
            else:
                logger.info("✓ All Chrome libraries found")
                results['missing_libraries'] = []
        except Exception as e:
            logger.error(f"ldd check failed: {e}")

        # Test 6: Try Chrome without user-data-dir first
        try:
            logger.info("Test 6a: Attempting minimal Chrome (no user-data-dir)...")
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service

            options = Options()
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--headless=new')

            service = Service('/usr/local/bin/chromedriver', log_output='/app/logs/chromedriver_test.log')
            test_driver = webdriver.Chrome(service=service, options=options)

            logger.info("✓ Chrome instance created successfully!")
            test_driver.get('about:blank')
            logger.info("✓ Navigated to about:blank")

            results['chrome_test_minimal'] = 'SUCCESS'

            test_driver.quit()
            logger.info("✓ Chrome instance closed")

        except Exception as e:
            results['chrome_test_minimal'] = 'FAILED'
            results['chrome_test_minimal_error'] = str(e)
            logger.error(f"✗ Minimal Chrome test failed: {e}")

        # Test 6b: Try Chrome WITH user-data-dir
        try:
            logger.info("Test 6b: Attempting Chrome with user-data-dir...")

            options = Options()
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--headless=new')
            options.add_argument(f'--user-data-dir={CHROME_USER_DATA_DIR}')

            service = Service('/usr/local/bin/chromedriver', log_output='/app/logs/chromedriver_userdata_test.log')
            test_driver = webdriver.Chrome(service=service, options=options)

            logger.info("✓ Chrome with user-data-dir created successfully!")
            test_driver.get('about:blank')
            logger.info("✓ Navigated to about:blank")

            results['chrome_test'] = 'SUCCESS'
            results['chrome_test_message'] = 'Chrome can be instantiated with user-data-dir'

            test_driver.quit()
            logger.info("✓ Chrome instance closed")

        except Exception as e:
            results['chrome_test'] = 'FAILED'
            results['chrome_test_error'] = str(e)
            logger.error(f"✗ Chrome with user-data-dir test failed: {e}")
            import traceback
            logger.error(traceback.format_exc())

        logger.info("=" * 80)
        logger.info("CHROME TEST COMPLETE")
        logger.info("=" * 80)

        return jsonify(results)

    except Exception as e:
        logger.error(f"Test endpoint error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    # Ensure download directory exists
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(CHROME_USER_DATA_DIR, exist_ok=True)

    logger.info("=" * 80)
    logger.info("Starting NAS Video Downloader")
    logger.info(f"Download directory: {DOWNLOAD_DIR}")
    logger.info(f"Chrome data directory: {CHROME_USER_DATA_DIR}")
    logger.info("=" * 80)

    app.run(host='0.0.0.0', port=5000, debug=False)
