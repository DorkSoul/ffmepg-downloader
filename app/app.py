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

# Configure logging to stdout/stderr for Docker logs
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/app/logs/flask.log')
    ]
)
logger = logging.getLogger(__name__)

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
                    resolution_info = {
                        'url': stream_url,
                        'bandwidth': int(attrs.get('BANDWIDTH', 0)),
                        'resolution': attrs.get('RESOLUTION', ''),
                        'framerate': attrs.get('FRAME-RATE', ''),
                        'codecs': attrs.get('CODECS', ''),
                        'name': attrs.get('IVS-NAME', attrs.get('STABLE-VARIANT-ID', ''))
                    }

                    resolutions.append(resolution_info)

        i += 1

    # Sort by bandwidth (highest first)
    resolutions.sort(key=lambda x: x['bandwidth'], reverse=True)

    return resolutions

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
    def __init__(self, browser_id, preferred_resolution='1080p60'):
        self.browser_id = browser_id
        self.driver = None
        self.detected_streams = []
        self.is_running = False
        self.download_started = False
        self.thumbnail_data = None
        self.preferred_resolution = preferred_resolution
        self.awaiting_resolution_selection = False
        self.available_resolutions = []
        self.selected_stream_url = None

    def start_browser(self, url):
        """Start Chrome with DevTools Protocol enabled"""
        try:
            logger.info(f"Starting Chrome browser for {url}")

            chrome_options = Options()
            # Essential flags for Docker
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-setuid-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')

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

            logger.info(f"Browser {self.browser_id} started successfully, navigating to {url}")
            self.driver.get(url)
            self.is_running = True

            # Start monitoring network traffic
            threading.Thread(target=self._monitor_network, daemon=True).start()

            logger.info(f"Browser {self.browser_id} fully initialized")
            return True
        except WebDriverException as e:
            logger.error(f"WebDriver error starting browser: {e}")
            logger.error(f"Error details: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error starting browser: {type(e).__name__}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def _monitor_network(self):
        """Monitor network traffic for video streams"""
        logger.info(f"Starting network monitoring for browser {self.browser_id}")

        while self.is_running and self.driver:
            try:
                logs = self.driver.get_log('performance')

                for entry in logs:
                    try:
                        log_data = json.loads(entry['message'])
                        message = log_data.get('message', {})
                        method = message.get('method', '')

                        # Look for network response events
                        if method == 'Network.responseReceived':
                            params = message.get('params', {})
                            response = params.get('response', {})
                            url = response.get('url', '')
                            mime_type = response.get('mimeType', '')

                            # Detect video streams
                            if self._is_video_stream(url, mime_type):
                                stream_info = {
                                    'url': url,
                                    'type': self._get_stream_type(url),
                                    'mime_type': mime_type,
                                    'timestamp': time.time()
                                }

                                if stream_info not in self.detected_streams:
                                    logger.info(f"Detected stream: {url}")
                                    self.detected_streams.append(stream_info)

                                    # Start download for the first valid stream
                                    if not self.download_started and not self.awaiting_resolution_selection:
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
        """Check if URL is a video stream"""
        video_extensions = ['.m3u8', '.mpd', '.mp4', '.ts', '.m4s']
        video_mime_types = ['video/', 'application/vnd.apple.mpegurl', 'application/dash+xml']

        # Check URL extension
        if any(url.lower().endswith(ext) or ext in url.lower() for ext in video_extensions):
            # Filter out ads and tracking
            if any(keyword in url.lower() for keyword in ['ad', 'doubleclick', 'analytics', 'tracking']):
                return False
            return True

        # Check MIME type
        if any(mime in mime_type.lower() for mime in video_mime_types):
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

                    # Try to match preferred resolution
                    matched = match_resolution(resolutions, self.preferred_resolution)

                    if matched:
                        # Found preferred resolution, start download
                        logger.info(f"Matched preferred resolution: {matched['name']}")
                        self._start_download_with_url(matched['url'], matched['name'])
                    else:
                        # No match, prompt user to select
                        logger.info(f"Preferred resolution {self.preferred_resolution} not found, awaiting user selection")
                        self.awaiting_resolution_selection = True
                        self.available_resolutions = resolutions
                else:
                    # Couldn't parse resolutions, just download the master URL
                    logger.warning("Could not parse resolutions from master playlist")
                    self._start_download(stream_info)
            else:
                # Not a master playlist, proceed with direct download
                logger.info("Not a master playlist, downloading directly")
                self._start_download(stream_info)
        else:
            # Not HLS, download directly
            self._start_download(stream_info)

    def _start_download(self, stream_info):
        """Start downloading the detected stream"""
        self._start_download_with_url(stream_info['url'], stream_info['type'])

    def _start_download_with_url(self, stream_url, resolution_name):
        """Start download with specific URL and resolution name"""
        self.download_started = True
        self.selected_stream_url = stream_url

        logger.info(f"Starting download for resolution: {resolution_name}")
        logger.info(f"Stream URL: {stream_url}")

        # Wait a moment for video to start playing
        logger.info("Waiting 3 seconds for video to load...")
        time.sleep(3)

        # Capture thumbnail
        self._capture_thumbnail()

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

        # Schedule auto-close
        threading.Thread(
            target=self._auto_close_browser,
            daemon=True
        ).start()

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

            # Store process info
            download_queue[self.browser_id] = {
                'process': process,
                'output_path': output_path,
                'stream_url': stream_url,
                'started_at': time.time()
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
            'available_resolutions': self.available_resolutions
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
        preferred_resolution = data.get('preferred_resolution', '1080p60')

        if not url:
            return jsonify({'error': 'No URL provided'}), 400

        logger.info(f"Starting browser with preferred resolution: {preferred_resolution}")

        # Generate browser ID
        browser_id = f"browser_{int(time.time())}"

        # Create and start detector with preferred resolution
        detector = StreamDetector(browser_id, preferred_resolution)
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
        stream_url = data.get('stream_url')
        resolution_name = data.get('resolution_name')

        if not all([browser_id, stream_url, resolution_name]):
            return jsonify({'error': 'Missing required parameters'}), 400

        if browser_id not in active_browsers:
            return jsonify({'error': 'Browser not found'}), 404

        detector = active_browsers[browser_id]

        logger.info(f"User selected resolution: {resolution_name}")
        logger.info(f"Stream URL: {stream_url}")

        # Clear awaiting state
        detector.awaiting_resolution_selection = False

        # Start download with selected resolution
        detector._start_download_with_url(stream_url, resolution_name)

        return jsonify({
            'success': True,
            'message': f'Starting download for {resolution_name}'
        })

    except Exception as e:
        logger.error(f"Resolution selection error: {e}")
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

                # Try to remove the directory with retries
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        logger.info(f"Removal attempt {attempt + 1}/{max_retries}")
                        shutil.rmtree(CHROME_USER_DATA_DIR)
                        logger.info("Chrome data directory removed")
                        break
                    except OSError as e:
                        if attempt < max_retries - 1:
                            logger.warning(f"Attempt {attempt + 1} failed: {e}, retrying...")
                            time.sleep(2)
                        else:
                            raise

                # Recreate the directory
                os.makedirs(CHROME_USER_DATA_DIR, exist_ok=True)
                logger.info("Chrome data directory recreated")

                return jsonify({
                    'success': True,
                    'message': 'Cookies and browser data cleared successfully'
                })
            except Exception as e:
                logger.error(f"Error clearing Chrome data: {e}")
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
