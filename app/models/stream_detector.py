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

    def __init__(self, browser_id, config, resolution='1080p', framerate='any', auto_download=False, filename=None, output_format='mp4'):
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
        self.output_format = output_format  # Output file format (mp4, mkv, mp3, etc.)
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
                
                # Essential flags for Docker
                chrome_options.add_argument('--no-sandbox')
                chrome_options.add_argument('--disable-setuid-sandbox')
                chrome_options.add_argument('--disable-dev-shm-usage')

                # Fix "Chrome did not shut down correctly" and session restore issues
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

                logger.info("Initializing ChromeDriver...")
                service = Service(
                    self.config.CHROMEDRIVER_PATH,
                    log_output=self.config.CHROMEDRIVER_LOG_PATH
                )

                try:
                    self.driver = webdriver.Chrome(service=service, options=chrome_options)
                    logger.info("Chrome started successfully")
                    
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

        # Navigate to URL with JS navigation to avoid session restore issues
        logger.info(f"Navigating to {url}")
        max_nav_attempts = 3
        for attempt in range(max_nav_attempts):
            try:
                # First, navigate to about:blank to reset any session restore state
                if attempt == 0:
                    self.driver.get('about:blank')
                    time.sleep(0.5)
                
                # Use JavaScript navigation for more forceful control
                try:
                    self.driver.execute_script(f'window.location.href = "{url}";')
                except Exception:
                    self.driver.get(url)
                
                time.sleep(1)
                current_url = self.driver.current_url
                
                # Verify we're not still on about:blank
                if current_url == 'about:blank' or 'about:blank' in current_url:
                    continue
                
                # Check if body has content (not just a blank white page)
                try:
                    body_len = self.driver.execute_script('return document.body ? document.body.innerHTML.length : 0')
                    if body_len < 100:
                        self.driver.refresh()
                        time.sleep(2)
                except Exception:
                    pass
                
                # Wait for page to be ready
                try:
                    WebDriverWait(self.driver, 10).until(
                        lambda d: d.execute_script('return document.readyState') in ['interactive', 'complete']
                    )
                except TimeoutException:
                    pass
                break
                    
            except Exception as e:
                logger.error(f"Navigation error on attempt {attempt + 1}: {e}")
                if attempt < max_nav_attempts - 1:
                    time.sleep(1)
                else:
                    logger.error("All navigation attempts failed")
             
        return True

    def _setup_cdp(self):
        """Setup Chrome DevTools Protocol connection"""
        try:
            # Get the debugger address from Chrome
            debugger_address = None
            if 'goog:chromeOptions' in self.driver.capabilities:
                debugger_address = self.driver.capabilities['goog:chromeOptions'].get('debuggerAddress')

            if debugger_address:
                # Query the debugger to get WebSocket URL
                debugger_url = f"http://{debugger_address}/json"
                try:
                    response = req_lib.get(debugger_url, timeout=5)
                    if response.status_code == 200:
                        pages = response.json()
                        if pages and len(pages) > 0:
                            self.ws_url = pages[0].get('webSocketDebuggerUrl')
                except Exception:
                    pass

            # Enable Network domain via execute_cdp_cmd
            self.driver.execute_cdp_cmd('Network.enable', {})

        except Exception as e:
            logger.warning(f"Could not set up CDP: {e}")

    def _cdp_websocket_listener(self):
        """Real-time CDP WebSocket listener"""

        def on_message(ws, message):
            """Handle incoming CDP messages"""
            try:
                data = json.loads(message)
                method = data.get('method', '')
                params = data.get('params', {})

                if method.startswith('Network.'):
                    self._handle_network_event(method, params, ws)
                elif method == 'Fetch.requestPaused':
                    self._handle_fetch_event(params, ws)

            except json.JSONDecodeError:
                pass
            except Exception as e:
                logger.error(f"CDP error: {e}")

        def on_error(ws, error):
            logger.error(f"CDP WebSocket error: {error}")

        def on_close(ws, close_status_code, close_msg):
            pass

        def on_open(ws):
            self._cdp_enable_domains(ws)

        try:
            self.ws = websocket.WebSocketApp(
                self.ws_url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            self.ws.run_forever()
        except Exception as e:
            logger.error(f"CDP WebSocket error: {e}")


    def _handle_network_event(self, method, params, ws):
        """Handle Network.* CDP events"""
        url = None
        mime_type = ''

        if method == 'Network.responseReceived':
            response = params.get('response', {})
            url = response.get('url', '')
            mime_type = response.get('mimeType', '')

            if self._is_video_stream(url, mime_type):
                self._add_detected_stream(url, mime_type)

    def _handle_fetch_event(self, params, ws):
        """Handle Fetch.requestPaused CDP events"""
        request = params.get('request', {})
        url = request.get('url', '')
        request_id = params.get('requestId', '')

        if 'm3u8' in url.lower():
            is_likely_master = self._is_likely_master_playlist(url)
            is_likely_media = self._is_likely_media_playlist(url)

            if not is_likely_media and (is_likely_master or not self.detected_streams):
                mime_type = 'application/vnd.apple.mpegurl'
                if self._is_video_stream(url, mime_type):
                    self._add_detected_stream(url, mime_type, stream_type='HLS')

        # Continue the request
        try:
            continue_cmd = {
                "id": self.cdp_session_id,
                "method": "Fetch.continueRequest",
                "params": {"requestId": request_id}
            }
            self.cdp_session_id += 1
            ws.send(json.dumps(continue_cmd))
        except Exception:
            pass

    def _cdp_enable_domains(self, ws):
        """Enable CDP domains for network monitoring"""
        try:
            # Network domain
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

        except Exception as e:
            logger.error(f"CDP enable error: {e}")

    def _monitor_network(self):
        """Monitor network traffic for video streams (legacy backup)"""
        while self.is_running and self.driver:
            try:
                logs = self.driver.get_log('performance')

                for entry in logs:
                    try:
                        log_data = json.loads(entry['message'])
                        message = log_data.get('message', {})
                        method = message.get('method', '')

                        if method == 'Network.responseReceived':
                            params = message.get('params', {})
                            response = params.get('response', {})
                            url = response.get('url', '')
                            mime_type = response.get('mimeType', '')

                            if self._is_video_stream(url, mime_type):
                                self._add_detected_stream(url, mime_type)

                    except json.JSONDecodeError:
                        continue
                    except Exception:
                        pass

                time.sleep(0.5)

            except Exception:
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

        if '.m3u8' in stream_url.lower():
            content = PlaylistParser.fetch_master_playlist(stream_url)

            if content and '#EXT-X-STREAM-INF:' in content:
                self._process_master_playlist(stream_url, content)
            else:
                self._process_single_stream(stream_url, stream_info)
        else:
            self._process_single_stream(stream_url, stream_info)

    def _process_master_playlist(self, stream_url, content):
        """Process a master playlist with multiple resolutions"""
        resolutions = PlaylistParser.parse_master_playlist(content)

        if resolutions:
            if self.auto_download:
                matched_stream = self._match_stream(resolutions)

                if matched_stream:
                    logger.info(f"Matched stream: {matched_stream['name']}")
                    self._enrich_and_add_thumbnail(matched_stream)
                    self._start_download_with_stream(matched_stream)
                else:
                    self._show_stream_selection(resolutions)
            else:
                self._show_stream_selection(resolutions)
        else:
            self._show_unparsed_stream(stream_url)

    def _process_single_stream(self, stream_url, stream_info):
        """Process a single stream (not a master playlist)"""
        stream_entry = {
            'url': stream_url,
            'bandwidth': 0,
            'resolution': '',
            'framerate': '',
            'codecs': '',
            'name': stream_info['type']
        }

        if self.auto_download:
            self._enrich_and_add_thumbnail(stream_entry)
            self._start_download_with_url(stream_url, stream_info['type'], stream_entry)
        else:
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

        def get_resolution_height(res):
            """Extract height from resolution string like '1920x1080' or from name like '1080p60'"""
            resolution_str = res.get('resolution', '')
            name = res.get('name', '').lower()
            
            # Try to extract from resolution field (e.g., "1920x1080")
            if 'x' in resolution_str:
                try:
                    return int(resolution_str.split('x')[1])
                except (ValueError, IndexError):
                    pass
            
            # Try to extract from name (e.g., "1080p60" -> 1080)
            import re
            match = re.search(r'(\d+)p', name)
            if match:
                return int(match.group(1))
            
            # Fallback to bandwidth as a proxy for quality
            return res.get('bandwidth', 0) // 1000000  # Convert to rough resolution estimate

        def get_framerate(res):
            """Extract framerate as a number"""
            fr = res.get('framerate', '')
            if fr:
                try:
                    return float(str(fr).split('.')[0])
                except (ValueError, AttributeError):
                    pass
            
            # Try to extract from name (e.g., "1080p60" -> 60)
            name = res.get('name', '').lower()
            import re
            match = re.search(r'p(\d+)', name)
            if match:
                return float(match.group(1))
            
            return 0.0

        # Extract target resolution
        target_res = self.resolution.lower().replace('p', '')

        # Special case: "source" means highest quality - sort by resolution height, then framerate
        if target_res == 'source':
            # Sort by resolution height (descending), then by framerate (descending)
            sorted_streams = sorted(
                resolutions,
                key=lambda x: (get_resolution_height(x), get_framerate(x)),
                reverse=True
            )
            best = sorted_streams[0]
            logger.info(f"Source requested: selected {best.get('name', 'unknown')} - {best.get('resolution', '?')}@{best.get('framerate', '?')}fps")
            return best

        # Filter by resolution first
        matching_res = [r for r in resolutions
                       if target_res in r.get('resolution', '').lower() or
                          target_res in r.get('name', '').lower()]

        if not matching_res:
            # No exact match - return highest quality overall
            sorted_streams = sorted(
                resolutions,
                key=lambda x: (get_resolution_height(x), get_framerate(x)),
                reverse=True
            )
            logger.info(f"No match for {self.resolution}, falling back to highest: {sorted_streams[0].get('name', 'unknown')}")
            return sorted_streams[0]

        # Sort matching streams by framerate (highest first)
        sorted_matching = sorted(matching_res, key=lambda x: get_framerate(x), reverse=True)

        # Filter by framerate preference
        if self.framerate == 'any':
            # Return highest framerate at the target resolution
            best = sorted_matching[0]
            logger.info(f"Matched {self.resolution} with highest framerate: {best.get('name', 'unknown')}@{best.get('framerate', '?')}fps")
            return best
        elif self.framerate == '60':
            fps_60 = [r for r in sorted_matching if get_framerate(r) >= 55]  # Allow some tolerance
            if fps_60:
                return fps_60[0]
            logger.info(f"No 60fps stream found for {self.resolution}")
            return None
        elif self.framerate == '30':
            fps_30 = [r for r in sorted_matching if 25 <= get_framerate(r) <= 35]  # Allow some tolerance
            if fps_30:
                return fps_30[0]
            logger.info(f"No 30fps stream found for {self.resolution}")
            return None

        return sorted_matching[0]

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
        except Exception:
            pass

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
        ext = self.output_format
        if self.filename:
            # Check if filename already has an extension
            if '.' in self.filename:
                filename = self.filename
            else:
                filename = f"{self.filename}.{ext}"
        else:
            timestamp = int(time.time())
            filename = f"video_{resolution_name}_{timestamp}.{ext}"

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
