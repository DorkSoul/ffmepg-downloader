import time
import json
import logging
import threading
import websocket
import requests as req_lib
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import os
import glob

from app.utils import PlaylistParser, MetadataExtractor, ThumbnailGenerator

logger = logging.getLogger(__name__)


class StreamDetector:
    """Detects and handles video streams from web pages using browser automation"""

    def __init__(self, browser_id, config, resolution='1080p', framerate='any', auto_download=False, filename=None):
        self.browser_id = browser_id
        self.config = config
        self.driver = None
        self.detected_streams = []
        self.is_running = False
        self.download_started = False
        self.thumbnail_data = None
        self.resolution = resolution
        self.framerate = framerate  # 'any', '60', '30'
        self.auto_download = auto_download
        self.filename = filename  # Optional custom filename
        self.awaiting_resolution_selection = False
        self.available_resolutions = []
        self.selected_stream_url = None
        # WebSocket CDP connection
        self.ws = None
        self.ws_url = None
        self.cdp_session_id = 1
        # Callback for when download needs to be started
        self.download_callback = None

    def set_download_callback(self, callback):
        """Set callback function for starting downloads"""
        self.download_callback = callback

    def start_browser(self, url):
        """Start Chrome with DevTools Protocol enabled"""
        max_retries = 2
        retry_count = 0

        while retry_count < max_retries:
            try:
                logger.info(f"Starting Chrome browser for {url}")

                chrome_options = Options()
                logger.info("Debug: Created chrome_options")
                
                # Essential flags for Docker
                chrome_options.add_argument('--no-sandbox')
                chrome_options.add_argument('--disable-setuid-sandbox')
                chrome_options.add_argument('--disable-dev-shm-usage')

                # Fix "Chrome did not shut down correctly" and session restore issues
                logger.info(f"Debug: Checking prefs in {self.config.CHROME_USER_DATA_DIR}")
                try:
                    prefs_path = os.path.join(self.config.CHROME_USER_DATA_DIR, 'Default', 'Preferences')
                    if os.path.exists(prefs_path):
                        with open(prefs_path, 'r', encoding='utf-8') as f:
                            prefs = json.load(f)
                        
                        # Reset crash flags and session restore settings
                        changed = False
                        
                        # Reset exit_type to Normal
                        if 'profile' in prefs:
                            if prefs['profile'].get('exit_type') != 'Normal':
                                prefs['profile']['exit_type'] = 'Normal'
                                changed = True
                            # Also reset exited_cleanly flag
                            if prefs['profile'].get('exited_cleanly') != True:
                                prefs['profile']['exited_cleanly'] = True
                                changed = True
                        
                        # Disable session restore (prevents blank window with highlighted URL)
                        if 'session' in prefs:
                            if prefs['session'].get('restore_on_startup') != 5:  # 5 = don't restore
                                prefs['session']['restore_on_startup'] = 5
                                changed = True
                        
                        # Also clear the startup URLs (another session restore mechanism)
                        if 'session' in prefs and 'startup_urls' in prefs['session']:
                            if prefs['session']['startup_urls']:
                                prefs['session']['startup_urls'] = []
                                changed = True
                        
                        if changed:
                            logger.info("Resetting Chrome crash flag and session restore settings in Preferences")
                            with open(prefs_path, 'w', encoding='utf-8') as f:
                                json.dump(prefs, f)
                except Exception as prefs_error:
                    logger.warning(f"Could not reset Chrome preferences: {prefs_error}")

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
                
                # Prevent session restore issues (blank window with highlighted URL)
                chrome_options.add_argument('--disable-session-crashed-bubble')
                chrome_options.add_argument('--disable-infobars')
                chrome_options.add_argument('--no-first-run')
                # Additional flags to prevent session/tab restore
                chrome_options.add_argument('--no-default-browser-check')
                chrome_options.add_argument('--disable-restore-session-state')
                chrome_options.add_argument('--disable-background-timer-throttling')
                # Start with about:blank to prevent session restore race condition
                chrome_options.add_argument('about:blank')

                # User data directory for cookie persistence
                chrome_options.add_argument(f'--user-data-dir={self.config.CHROME_USER_DATA_DIR}')

                # Logging
                chrome_options.add_argument('--enable-logging')
                chrome_options.add_argument('--v=1')

                chrome_options.add_experimental_option('w3c', True)
                chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])

                # Enable performance logging to capture network events
                chrome_options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

                logger.info("Initializing ChromeDriver service")
                service = Service(
                    self.config.CHROMEDRIVER_PATH,
                    log_output=self.config.CHROMEDRIVER_LOG_PATH
                )

                logger.info("Creating Chrome webdriver instance...")
                logger.debug(f"Chrome options: {[arg for arg in chrome_options.arguments]}")

                try:
                    self.driver = webdriver.Chrome(service=service, options=chrome_options)
                    logger.info("Chrome webdriver created successfully!")
                    
                    # Set page load timeout to prevent hangs
                    self.driver.set_page_load_timeout(60)
                    
                except Exception as driver_error:
                    logger.error(f"Failed to create Chrome webdriver: {driver_error}")

                    # If this is the first attempt and error mentions "Chrome instance exited"
                    if retry_count == 0 and "Chrome instance exited" in str(driver_error):
                        logger.warning("Chrome failed to start with user-data-dir, cleaning lock files and retrying...")
                        retry_count += 1

                        # Clean up problematic lock files in user-data-dir
                        try:
                            lock_files = glob.glob(os.path.join(self.config.CHROME_USER_DATA_DIR, '**/SingletonLock'), recursive=True)
                            lock_files.extend(glob.glob(os.path.join(self.config.CHROME_USER_DATA_DIR, '**/lockfile'), recursive=True))

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
        self._setup_cdp()

        self.is_running = True

        # Start WebSocket CDP listener BEFORE navigating to catch initial requests
        if self.ws_url:
            threading.Thread(target=self._cdp_websocket_listener, daemon=True).start()
            # Give WebSocket a moment to connect
            time.sleep(0.5)
        else:
            logger.warning("No WebSocket URL available, falling back to polling only")

        # Start monitoring network traffic (legacy polling as backup)
        threading.Thread(target=self._monitor_network, daemon=True).start()

        # Navigate to URL with explicit wait and retry logic
        # This fixes a race condition where session restore interferes with navigation
        logger.info(f"[NAV] Starting navigation to: {url}")
        max_nav_attempts = 3
        for attempt in range(max_nav_attempts):
            try:
                # First, navigate to about:blank to reset any session restore state
                if attempt == 0:
                    logger.info("[NAV] Navigating to about:blank first to clear any restore state")
                    self.driver.get('about:blank')
                    time.sleep(0.3)
                
                logger.info(f"[NAV] Attempt {attempt + 1}/{max_nav_attempts}: Loading {url}")
                self.driver.get(url)
                
                # Wait for page to actually start loading
                time.sleep(0.5)
                
                # Check if URL changed from about:blank
                current_url = self.driver.current_url
                logger.info(f"[NAV] Current URL after navigation: {current_url}")
                
                # Verify we're not still on about:blank and URL contains expected domain
                if current_url == 'about:blank' or 'about:blank' in current_url:
                    logger.warning(f"[NAV] Still on about:blank, retrying...")
                    continue
                
                # Try to wait for page readyState to be 'loading' or 'complete'
                try:
                    WebDriverWait(self.driver, 10).until(
                        lambda d: d.execute_script('return document.readyState') in ['interactive', 'complete']
                    )
                    logger.info(f"[NAV] ✓ Page loaded successfully: {self.driver.current_url[:80]}")
                    break
                except TimeoutException:
                    logger.warning(f"[NAV] Page load timeout, but continuing (page may still be loading)")
                    break
                    
            except Exception as e:
                logger.error(f"[NAV] Error on attempt {attempt + 1}: {e}")
                if attempt < max_nav_attempts - 1:
                    logger.info(f"[NAV] Retrying navigation...")
                    time.sleep(1)
                else:
                    logger.error(f"[NAV] All navigation attempts failed")
             
        return True

    def _setup_cdp(self):
        """Setup Chrome DevTools Protocol connection"""
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

    def _cdp_websocket_listener(self):
        """Real-time CDP WebSocket listener"""

        def on_message(ws, message):
            """Handle incoming CDP messages - capture ALL network activity"""
            try:
                data = json.loads(message)
                method = data.get('method', '')
                params = data.get('params', {})

                # Log ALL Network events
                if method.startswith('Network.'):
                    self._handle_network_event(method, params, ws)

                # Handle Fetch events (modern video players use fetch/XHR)
                elif method == 'Fetch.requestPaused':
                    self._handle_fetch_event(params, ws)

            except json.JSONDecodeError as e:
                logger.error(f"[CDP-WS] JSON decode error: {e}")
            except Exception as e:
                logger.error(f"[CDP-WS] Error processing message: {e}")

        def on_error(ws, error):
            logger.error(f"[CDP-WS] WebSocket error: {error}")

        def on_close(ws, close_status_code, close_msg):
            logger.info(f"[CDP-WS] WebSocket closed: {close_status_code} - {close_msg}")

        def on_open(ws):
            logger.info("CDP WebSocket OPEN CONNECTED!")
            self._cdp_enable_domains(ws)

        # Connect to WebSocket
        try:
            logger.info(f"Connecting to CDP WebSocket: {self.ws_url[:50]}...")
            self.ws = websocket.WebSocketApp(
                self.ws_url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            
            self.ws.run_forever()
        except Exception as e:
            logger.error(f"Error checking stream: {e}")


    def _handle_network_event(self, method, params, ws):
        """Handle Network.* CDP events"""
        url = None
        mime_type = ''

        if method == 'Network.requestWillBeSent':
            request = params.get('request', {})
            url = request.get('url', '')
            request_method = request.get('method', '')
            request_id = params.get('requestId', '')

            if 'm3u8' in url.lower():
                logger.info(f"[CDP-WS] 🔍 REQUEST (m3u8): {request_method} {url}")
                logger.info(f"[CDP-WS]   └─ RequestID: {request_id}")

        elif method == 'Network.responseReceived':
            response = params.get('response', {})
            url = response.get('url', '')
            mime_type = response.get('mimeType', '')
            status = response.get('status', '')

            if 'm3u8' in url.lower() or 'mpegurl' in mime_type.lower():
                logger.info(f"[CDP-WS] 🎯 RESPONSE (m3u8): Status={status} | MIME={mime_type}")
                logger.info(f"[CDP-WS]   └─ URL: {url}")

                # Process this as a detected stream
                if self._is_video_stream(url, mime_type):
                    self._add_detected_stream(url, mime_type)

    def _handle_fetch_event(self, params, ws):
        """Handle Fetch.requestPaused CDP events"""
        request = params.get('request', {})
        url = request.get('url', '')
        request_id = params.get('requestId', '')

        # Check for m3u8 playlists
        if 'm3u8' in url.lower():
            is_likely_master = self._is_likely_master_playlist(url)
            is_likely_media = self._is_likely_media_playlist(url)

            # Only process master playlists
            if not is_likely_media and (is_likely_master or not self.detected_streams):
                logger.info(f"Detected master playlist: {url[:100]}...")

                # Process this as a detected stream
                mime_type = 'application/vnd.apple.mpegurl'
                if self._is_video_stream(url, mime_type):
                    self._add_detected_stream(url, mime_type, stream_type='HLS')

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

    def _cdp_enable_domains(self, ws):
        """Enable all CDP domains for network monitoring"""
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

            # Page domain
            page_enable_cmd = {
                "id": self.cdp_session_id,
                "method": "Page.enable",
                "params": {}
            }
            self.cdp_session_id += 1
            ws.send(json.dumps(page_enable_cmd))

            # Fetch domain
            fetch_enable_cmd = {
                "id": self.cdp_session_id,
                "method": "Fetch.enable",
                "params": {
                    "patterns": [{"urlPattern": "*", "requestStage": "Request"}]
                }
            }
            self.cdp_session_id += 1
            ws.send(json.dumps(fetch_enable_cmd))

            # Runtime domain
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

    def _monitor_network(self):
        """Monitor network traffic for video streams (legacy backup)"""
        loop_count = 0

        while self.is_running and self.driver:
            try:
                logs = self.driver.get_log('performance')
                loop_count += 1

                # Log every 2 minutes to show we're alive
                if loop_count % 240 == 0:
                    logger.info(f"[LEGACY-POLL] Loop #{loop_count}, monitoring active")

                for entry in logs:
                    try:
                        log_data = json.loads(entry['message'])
                        message = log_data.get('message', {})
                        method = message.get('method', '')

                        # Check Network.responseReceived events
                        if method == 'Network.responseReceived':
                            params = message.get('params', {})
                            response = params.get('response', {})
                            url = response.get('url', '')
                            mime_type = response.get('mimeType', '')

                            # Only log .m3u8 files
                            if '.m3u8' in url.lower() or 'mpegurl' in mime_type.lower():
                                logger.info(f"[LEGACY-POLL] 🔍 Found .m3u8: {url[:200]}...")

                            # Detect video streams
                            if self._is_video_stream(url, mime_type):
                                self._add_detected_stream(url, mime_type)

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

        # Filter out individual segment files
        if url.lower().endswith('.ts') or url.lower().endswith('.m4s') or '/segment/' in url.lower():
            return False

        # HIGH PRIORITY: Twitch HLS API endpoint
        if 'usher.ttvnw.net' in url.lower() and '.m3u8' in url.lower():
            logger.info(f"✓✓✓ TWITCH HLS API DETECTED: {url[:150]}...")
            return True

        # Check for playlist extensions
        if any(url.lower().endswith(ext) or f'{ext}?' in url.lower() for ext in playlist_extensions):
            # Filter out ads and tracking
            if any(keyword in url.lower() for keyword in ['doubleclick', 'analytics', 'tracking']):
                return False
            return True

        # Check for playlist in path
        if 'playlist' in url.lower() and '.m3u8' in url.lower():
            return True

        # Check MIME type for playlists
        if any(mime in mime_type.lower() for mime in playlist_mime_types):
            return True

        return False

    def _is_likely_master_playlist(self, url):
        """Check if URL is likely a master playlist"""
        return (
            'usher' in url.lower() or
            'master' in url.lower() or
            '/playlist.m3u8' in url.lower() or
            '/index.m3u8' in url.lower() or
            'api' in url.lower()
        )

    def _is_likely_media_playlist(self, url):
        """Check if URL is likely a media playlist (not master)"""
        return (
            '/chunklist' in url.lower() or
            '/media_' in url.lower() or
            '/segment' in url.lower()
        )

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

    def _add_detected_stream(self, url, mime_type, stream_type=None):
        """Add a detected stream and trigger processing"""
        if stream_type is None:
            stream_type = self._get_stream_type(url)

        stream_info = {
            'url': url,
            'type': stream_type,
            'mime_type': mime_type,
            'timestamp': time.time()
        }

        if stream_info not in self.detected_streams:
            logger.info(f"✓ DETECTED STREAM: type={stream_info['type']}")
            self.detected_streams.append(stream_info)

            # Start download for the first valid stream
            if not self.download_started and not self.awaiting_resolution_selection:
                logger.info(f"Processing detected stream...")
                self._handle_stream_detection(stream_info)

    def _handle_stream_detection(self, stream_info):
        """Handle detected stream - check if it's a master playlist"""
        stream_url = stream_info['url']

        # Check if this is an HLS stream
        if '.m3u8' in stream_url.lower():
            logger.info(f"Detected .m3u8 stream, checking if it's a master playlist...")

            # Fetch and check if it's a master playlist
            content = PlaylistParser.fetch_master_playlist(stream_url)

            if content and '#EXT-X-STREAM-INF:' in content:
                logger.info("This is a master playlist! Parsing resolutions...")
                self._process_master_playlist(stream_url, content)
            else:
                # Not a master playlist
                self._process_single_stream(stream_url, stream_info)
        else:
            # Not HLS
            self._process_single_stream(stream_url, stream_info)

    def _process_master_playlist(self, stream_url, content):
        """Process a master playlist with multiple resolutions"""
        resolutions = PlaylistParser.parse_master_playlist(content)

        if resolutions:
            logger.info(f"Found {len(resolutions)} resolutions")

            if self.auto_download:
                logger.info("Auto-download enabled, finding matching stream...")
                matched_stream = self._match_stream(resolutions)

                if matched_stream:
                    logger.info(f"Matched stream: {matched_stream['name']}")
                    self._enrich_and_add_thumbnail(matched_stream)
                    self._start_download_with_stream(matched_stream)
                else:
                    logger.warning("No matching stream found, showing all streams")
                    self._show_stream_selection(resolutions)
            else:
                # Manual mode
                self._show_stream_selection(resolutions)
        else:
            # Couldn't parse resolutions
            self._show_unparsed_stream(stream_url)

    def _process_single_stream(self, stream_url, stream_info):
        """Process a single stream (not a master playlist)"""
        logger.info("Treating as single stream")
        stream_entry = {
            'url': stream_url,
            'bandwidth': 0,
            'resolution': '',
            'framerate': '',
            'codecs': '',
            'name': stream_info['type']
        }

        if self.auto_download:
            logger.info("Auto-download enabled, downloading single stream")
            self._enrich_and_add_thumbnail(stream_entry)
            self._start_download_with_url(stream_url, stream_info['type'], stream_entry)
        else:
            logger.info("Manual mode, showing single stream for selection")
            self._show_stream_selection([stream_entry])

    def _show_stream_selection(self, resolutions):
        """Show streams for manual selection"""
        self.awaiting_resolution_selection = True
        self.available_resolutions = resolutions

        # Enrich metadata and generate thumbnails in background (first 5 streams)
        for res in resolutions[:5]:
            threading.Thread(
                target=self._enrich_and_add_thumbnail,
                args=(res,),
                daemon=True
            ).start()

    def _show_unparsed_stream(self, stream_url):
        """Show unparsed master playlist"""
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
        threading.Thread(
            target=self._enrich_and_add_thumbnail,
            args=(stream_entry,),
            daemon=True
        ).start()

    def _match_stream(self, resolutions):
        """Find best matching stream based on resolution and framerate preferences"""
        if not resolutions:
            return None

        logger.info(f"Matching stream - Resolution: {self.resolution}, Framerate: {self.framerate}")

        # Extract target resolution
        target_res = self.resolution.lower().replace('p', '')

        # Special case: "source" means highest quality
        if target_res == 'source':
            return resolutions[0]

        # Filter by resolution first
        matching_res = [r for r in resolutions
                       if target_res in r.get('resolution', '').lower() or
                          target_res in r.get('name', '').lower()]

        if not matching_res:
            logger.warning(f"No streams found matching resolution {self.resolution}")
            return resolutions[0]

        # Filter by framerate
        if self.framerate == 'any':
            return matching_res[0]
        elif self.framerate == '60':
            fps_60 = [r for r in matching_res if '60' in str(r.get('framerate', ''))]
            return fps_60[0] if fps_60 else None
        elif self.framerate == '30':
            fps_30 = [r for r in matching_res if '30' in str(r.get('framerate', ''))]
            return fps_30[0] if fps_30 else None

        return matching_res[0]

    def _enrich_and_add_thumbnail(self, stream_dict):
        """Enrich stream metadata and add thumbnail"""
        try:
            # Enrich metadata
            MetadataExtractor.enrich_stream_metadata(stream_dict)

            # Add thumbnail
            stream_url = stream_dict.get('url')
            if stream_url:
                thumbnail = ThumbnailGenerator.generate_stream_thumbnail(stream_url)
                if thumbnail:
                    stream_dict['thumbnail'] = thumbnail
                    logger.info(f"Added thumbnail to stream: {stream_dict.get('name', 'unknown')}")
        except Exception as e:
            logger.error(f"Error enriching stream data: {e}")

    def _start_download_with_stream(self, stream):
        """Start download with stream object"""
        resolution_name = stream.get('name', 'video')
        self._start_download_with_url(stream['url'], resolution_name, stream)

    def _start_download_with_url(self, stream_url, resolution_name, stream_metadata=None):
        """Start download with specific URL"""
        self.download_started = True
        self.selected_stream_url = stream_url
        self.selected_stream_metadata = stream_metadata

        logger.info(f"Starting download for resolution: {resolution_name}")

        # Reuse thumbnail if available
        if stream_metadata and 'thumbnail' in stream_metadata:
            thumbnail = stream_metadata['thumbnail']
            if thumbnail.startswith('data:image/'):
                self.thumbnail_data = thumbnail.split(',', 1)[1]
            else:
                self.thumbnail_data = thumbnail

        # Generate filename
        if self.filename:
            filename = self.filename if self.filename.endswith('.mp4') else f"{self.filename}.mp4"
        else:
            timestamp = int(time.time())
            filename = f"video_{resolution_name}_{timestamp}.mp4"

        # Call download callback if set
        if self.download_callback:
            self.download_callback(self.browser_id, stream_url, filename, resolution_name, stream_metadata)

        # Wait for video to load
        time.sleep(3)

        # Capture thumbnail if not available
        if not self.thumbnail_data:
            self.thumbnail_data = ThumbnailGenerator.capture_screenshot(self.driver)

    def close(self):
        """Close the browser"""
        self.is_running = False

        # Close WebSocket connection
        if self.ws:
            try:
                self.ws.close()
            except Exception as e:
                logger.error(f"Error closing WebSocket: {e}")

        if self.driver:
            try:
                self.driver.quit()
                logger.info(f"Browser {self.browser_id} closed")
            except Exception as e:
                logger.error(f"Error closing browser: {e}")

    def get_status(self):
        """Get current status"""
        return {
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
