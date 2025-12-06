import os
import time
import logging
import subprocess
import shutil
from app.models import StreamDetector

logger = logging.getLogger(__name__)


class BrowserService:
    """Manages browser instances and stream detection"""

    def __init__(self, config, download_service):
        self.config = config
        self.download_service = download_service
        self.active_browsers = {}

    def start_browser(self, url, browser_id, resolution='1080p', framerate='any', auto_download=False, filename=None):
        """Start a browser instance for stream detection"""
        # Enforce singleton: Close ALL existing browsers first to free up the profile
        if self.active_browsers:
            logger.info("Closing existing browsers to enforce singleton session...")
            browsers_to_close = list(self.active_browsers.keys())
            for bid in browsers_to_close:
                self.close_browser(bid)
            # Short wait to ensure processes clean up
            time.sleep(1)

        detector = StreamDetector(
            browser_id,
            self.config,
            resolution,
            framerate,
            auto_download,
            filename
        )

        # Set download callback
        detector.set_download_callback(self.download_service.start_download)

        self.active_browsers[browser_id] = detector

        if detector.start_browser(url):
            return True, detector
        else:
            if browser_id in self.active_browsers:
                del self.active_browsers[browser_id]
            return False, None

    def close_browser(self, browser_id):
        """Close a specific browser instance"""
        if browser_id in self.active_browsers:
            detector = self.active_browsers[browser_id]
            detector.close()
            del self.active_browsers[browser_id]
            return True
        return False

    def get_browser_status(self, browser_id):
        """Get status of a specific browser"""
        if browser_id in self.active_browsers:
            return self.active_browsers[browser_id].get_status()
        return None

    def get_browser(self, browser_id):
        """Get a browser instance"""
        return self.active_browsers.get(browser_id)

    def select_resolution(self, browser_id, stream):
        """Handle manual resolution selection"""
        if browser_id not in self.active_browsers:
            return False, "Browser not found"

        detector = self.active_browsers[browser_id]

        logger.info(f"User selected resolution: {stream.get('name')}")

        # Enrich metadata before download
        from app.utils import MetadataExtractor
        MetadataExtractor.enrich_stream_metadata(stream)

        # Clear awaiting state
        detector.awaiting_resolution_selection = False

        # Start download
        detector._start_download_with_stream(stream)

        return True, f'Starting download for {stream.get("name")}'

    def select_stream(self, browser_id, stream_url):
        """Handle manual stream selection"""
        if browser_id not in self.active_browsers:
            return False, "Browser not found"

        detector = self.active_browsers[browser_id]

        # Find stream object
        selected_stream = None
        for res in detector.available_resolutions:
            if res['url'] == stream_url:
                selected_stream = res
                break

        if not selected_stream:
            selected_stream = {
                'url': stream_url,
                'name': 'selected_stream',
                'resolution': '',
                'framerate': '',
                'codecs': ''
            }

        stream_name = selected_stream.get('name', 'selected_stream')

        # Enrich metadata
        from app.utils import MetadataExtractor
        MetadataExtractor.enrich_stream_metadata(selected_stream)

        # Clear awaiting state
        detector.awaiting_resolution_selection = False

        # Start download
        detector._start_download_with_url(stream_url, stream_name, selected_stream)

        return True, f'Starting download for {stream_name}'

    def clear_cookies(self):
        """Clear Chrome cookies and profile data"""
        try:
            logger.info("Clear cookies requested")

            # Close all active browsers
            browsers_to_close = list(self.active_browsers.keys())
            for browser_id in browsers_to_close:
                try:
                    self.close_browser(browser_id)
                    logger.info(f"Closed browser {browser_id}")
                except Exception as e:
                    logger.error(f"Error closing browser {browser_id}: {e}")

            # Force kill Chrome processes
            try:
                subprocess.run(['pkill', '-9', 'chrome'], check=False, timeout=5)
                subprocess.run(['pkill', '-9', 'chromedriver'], check=False, timeout=5)
            except Exception:
                pass

            # Wait for processes to terminate
            time.sleep(3)

            if os.path.exists(self.config.CHROME_USER_DATA_DIR):
                try:

                    cleared_count = 0
                    failed_count = 0

                    for item in os.listdir(self.config.CHROME_USER_DATA_DIR):
                        item_path = os.path.join(self.config.CHROME_USER_DATA_DIR, item)
                        try:
                            if os.path.isfile(item_path) or os.path.islink(item_path):
                                os.unlink(item_path)
                                cleared_count += 1
                            elif os.path.isdir(item_path):
                                try:
                                    shutil.rmtree(item_path)
                                    cleared_count += 1
                                except OSError:
                                    # Try to clear contents
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
                        except Exception as item_error:
                            logger.error(f"Failed to remove {item}: {item_error}")
                            failed_count += 1

                    logger.info(f"Chrome data cleared: {cleared_count} items")

                    return True, f'Cookies cleared: {cleared_count} items removed'

                except Exception as e:
                    logger.error(f"Error clearing Chrome data: {e}")
                    return False, f'Failed to clear Chrome data: {str(e)}'
            else:
                os.makedirs(self.config.CHROME_USER_DATA_DIR, exist_ok=True)
                return True, 'Chrome data directory created (was not present)'

        except Exception as e:
            logger.error(f"Clear cookies error: {e}")
            return False, str(e)

    def check_chrome_installation(self):
        """Check Chrome and ChromeDriver installation"""
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
            logger.info(f"Download dir exists: {os.path.exists(self.config.DOWNLOAD_DIR)}")
            logger.info(f"Chrome data dir exists: {os.path.exists(self.config.CHROME_USER_DATA_DIR)}")

            return True
        except Exception as e:
            logger.error(f"Chrome installation check failed: {e}")
            return False
