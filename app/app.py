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

class StreamDetector:
    def __init__(self, browser_id):
        self.browser_id = browser_id
        self.driver = None
        self.detected_streams = []
        self.is_running = False
        self.download_started = False
        self.thumbnail_data = None

    def start_browser(self, url):
        """Start Chrome with DevTools Protocol enabled"""
        try:
            logger.info(f"Starting Chrome browser for {url}")

            chrome_options = Options()
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--disable-software-rasterizer')
            chrome_options.add_argument('--disable-extensions')
            chrome_options.add_argument('--disable-background-networking')
            chrome_options.add_argument('--disable-sync')
            chrome_options.add_argument('--disable-translate')
            chrome_options.add_argument('--disable-default-apps')
            chrome_options.add_argument('--remote-debugging-port=9222')
            chrome_options.add_argument(f'--user-data-dir={CHROME_USER_DATA_DIR}')
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
                                    if not self.download_started:
                                        self._start_download(stream_info)

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

    def _start_download(self, stream_info):
        """Start downloading the detected stream"""
        self.download_started = True

        # Capture thumbnail
        self._capture_thumbnail()

        # Generate filename
        timestamp = int(time.time())
        filename = f"video_{timestamp}.mp4"
        output_path = os.path.join(DOWNLOAD_DIR, filename)

        # Start FFmpeg download in background
        threading.Thread(
            target=self._download_with_ffmpeg,
            args=(stream_info['url'], output_path),
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
        return {
            'browser_id': self.browser_id,
            'is_running': self.is_running,
            'download_started': self.download_started,
            'detected_streams': len(self.detected_streams),
            'thumbnail': self.thumbnail_data,
            'latest_stream': self.detected_streams[-1] if self.detected_streams else None
        }


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

        if not url:
            return jsonify({'error': 'No URL provided'}), 400

        # Generate browser ID
        browser_id = f"browser_{int(time.time())}"

        # Create and start detector
        detector = StreamDetector(browser_id)
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

        # Test 4: Try to create minimal Chrome instance
        try:
            logger.info("Attempting to create minimal Chrome instance...")
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service

            options = Options()
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--headless')

            service = Service('/usr/local/bin/chromedriver')
            test_driver = webdriver.Chrome(service=service, options=options)

            logger.info("✓ Chrome instance created successfully!")
            test_driver.get('about:blank')
            logger.info("✓ Navigated to about:blank")

            results['chrome_test'] = 'SUCCESS'
            results['chrome_test_message'] = 'Chrome can be instantiated'

            test_driver.quit()
            logger.info("✓ Chrome instance closed")

        except Exception as e:
            results['chrome_test'] = 'FAILED'
            results['chrome_test_error'] = str(e)
            logger.error(f"✗ Chrome test failed: {e}")
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
