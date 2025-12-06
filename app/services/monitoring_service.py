import os
import json
import time
import threading
import logging
import uuid
import queue
import random

logger = logging.getLogger(__name__)

class MonitoringService:
    """Service to monitor streams using BrowserService"""

    def __init__(self, browser_service, download_service, config_dir):
        self.browser_service = browser_service
        self.download_service = download_service
        self.config_dir = config_dir
        self.streams_file = os.path.join(config_dir, 'monitored_streams.json')
        self.monitored_streams = {}  # id -> stream_dict
        self.active_downloads = {}   # stream_id -> browser_id
        
        self.stop_event = threading.Event()
        self.monitor_thread = None
        self.current_check_browser_id = None
        
        # Load streams from file
        self._load_streams()

    def start_monitoring(self):
        """Start the background monitoring thread"""
        if self.monitor_thread is None or not self.monitor_thread.is_alive():
            self.stop_event.clear()
            self.monitor_thread = threading.Thread(
                target=self._monitor_loop,
                daemon=True,
                name="StreamMonitorThread"
            )
            self.monitor_thread.start()
            logger.info("Browser-based monitoring started")

    def stop_monitoring(self):
        """Stop the background monitoring thread"""
        if self.monitor_thread:
            self.stop_event.set()
            self.monitor_thread.join(timeout=5)
            logger.info("Monitoring stopped")

    def add_stream(self, url, name=None):
        """Add a stream to monitor"""
        stream_id = str(uuid.uuid4())
        if not name:
            name = url.split('/')[-1]

        stream_entry = {
            'id': stream_id,
            'url': url,
            'name': name,
            'added_at': time.time(),
            'last_check': 0,
            'next_check_time': 0,  # Ready to check immediately
            'is_live': False,
            'last_live': 0
        }
        
        self.monitored_streams[stream_id] = stream_entry
        self._save_streams()
        return stream_entry

    def remove_stream(self, stream_id):
        """Remove a monitored stream"""
        if stream_id in self.monitored_streams:
            del self.monitored_streams[stream_id]
            self._save_streams()
            return True
        return False

    def get_streams(self):
        """Get all monitored streams"""
        return list(self.monitored_streams.values())

    def _monitor_loop(self):
        """Main monitoring loop"""
        logger.info("Monitoring loop started")
        
        while not self.stop_event.is_set():
            try:
                # 1. Active Downloads Maintenance
                # Remove downloads that are finished or stopped
                self._clean_active_downloads()

                # 2. Pick next stream to check
                # Prioritize streams that haven't been checked in a while
                now = time.time()
                streams_to_check = []
                for s in self.monitored_streams.values():
                    # Don't check if already downloading
                    if s['id'] in self.active_downloads:
                        continue
                        
                    # Check if it's time to check this stream
                    # Default to 0 if missing (backward compatibility) to check immediately
                    next_check = s.get('next_check_time', 0)
                    if now >= next_check: 
                        streams_to_check.append(s)

                if streams_to_check:
                    # Sort by last_check (oldest first)
                    streams_to_check.sort(key=lambda x: x.get('last_check', 0))
                    target_stream = streams_to_check[0]
                    
                    self._check_stream_with_browser(target_stream)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
            
            # Wait a bit before next iteration
            # If we just checked a stream, we probably waited inside the check method.
            # If no stream was ready, wait a few seconds.
            if self.stop_event.wait(5):
                break

    def _check_stream_with_browser(self, stream):
        """Open browser and check a single stream"""
        logger.info(f"Checking stream: {stream['name']} ({stream['url']})")
        stream['last_check'] = time.time()
        
        # Calculate next check time with jitter (7-11 minutes)
        # 7 minutes = 420 seconds
        # 11 minutes = 660 seconds
        delay = random.randint(420, 660)
        stream['next_check_time'] = time.time() + delay
        logger.info(f"Next check for {stream['name']} scheduled in {int(delay/60)} minutes")

        self._save_streams()

        browser_id = f"monitor_{stream['id']}"
        self.current_check_browser_id = browser_id

        try:
            # Start browser in auto-download mode
            # This uses the existing logic: open url -> detect m3u8 -> download
            # We want to intercept the download callback though? 
            # BrowserService.start_browser sets the callback to download_service.start_download.
            # We want to know if it started.
            
            # We'll rely on polling the browser status to see if 'download_started' becomes True.
            success, detector = self.browser_service.start_browser(
                url=stream['url'],
                browser_id=browser_id,
                resolution='1080p', # Prefer high quality
                framerate='any',
                auto_download=True,
                filename=None, # Auto-name
                output_format='mp4'
            )
            
            if not success:
                logger.error(f"Failed to start browser for {stream['name']}")
                return

            # Wait and Monitor (e.g. for 45 seconds)
            # If stream detected -> Download starts -> Browser might stay open or close?
            # In auto-download mode, the StreamDetector triggers download.
            
            check_duration = 45 
            start_wait = time.time()
            download_triggered = False
            
            while time.time() - start_wait < check_duration:
                if self.stop_event.is_set():
                    break
                    
                status = detector.get_status()
                
                if status['download_started']:
                    logger.info(f"Stream detected and download started: {stream['name']}")
                    stream['is_live'] = True
                    stream['last_live'] = time.time()
                    download_triggered = True
                    
                    # Track this active download
                    # The browser_id here is what the download service uses?
                    # StreamDetector calls callback with `browser_id`.
                    # So yes, we can track it.
                    self.active_downloads[stream['id']] = browser_id
                    break
                
                if not status['is_running']:
                    logger.warning("Browser closed unexpectedly")
                    break
                    
                time.sleep(1)

            if not download_triggered:
                logger.info(f"No stream detected for {stream['name']} (Timeout)")
                stream['is_live'] = False
                
                # Close the browser since we are done checking
                self.browser_service.close_browser(browser_id)
            else:
                # If download triggered, the browser might need to stay open 
                # depending on how data is fetched.
                # If it's a direct m3u8 download handled by ffmpeg in background, 
                # we technically CAN close the browser IF cookies aren't needed constantly.
                # But safer to leave it open or let the user decide?
                # Actually, our current DownloadService runs ffmpeg. 
                # Once ffmpeg starts, it usually doesn't need the browser UNLESS headers/cookies are needed.
                # The detector grabs headers.
                # So we can potentially close the browser to save resources, 
                # BUT if we close it immediately, we might lose session context? 
                # Let's close it to keep "Monitoring" lightweight-ish.
                # Wait... if we close it, we might kill the session.
                # Let's check `clean_active_downloads` logic.
                
                # For now, let's Close it. `yt-dlp` / `ffmpeg` should handle the stream with the headers we passed.
                logger.info("Closing browser after download trigger to save resources...")
                self.browser_service.close_browser(browser_id)

        except Exception as e:
            logger.error(f"Error checking stream {stream['name']}: {e}")
            self.browser_service.close_browser(browser_id)
        
        self.current_check_browser_id = None
        self._save_streams()

    def _clean_active_downloads(self):
        """Check active downloads and remove finished ones from tracking"""
        active_list = self.download_service.get_active_downloads()
        active_browser_ids = {d['browser_id'] for d in active_list if d['is_running']}
        
        for stream_id, browser_id in list(self.active_downloads.items()):
            if browser_id not in active_browser_ids:
                logger.info(f"Download finished for monitored stream: {stream_id}")
                del self.active_downloads[stream_id]

    def _load_streams(self):
        try:
            if os.path.exists(self.streams_file):
                with open(self.streams_file, 'r') as f:
                    data = json.load(f)
                    self.monitored_streams = {s['id']: s for s in data}
        except Exception as e:
            logger.error(f"Error loading streams: {e}")

    def _save_streams(self):
        try:
            with open(self.streams_file, 'w') as f:
                json.dump(list(self.monitored_streams.values()), f, indent=4)
        except Exception:
            pass
