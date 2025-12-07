import os
import time
import json
import logging
import threading
import random
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class Scheduler:
    """Manages scheduled stream checks"""

    def __init__(self, config, browser_service):
        self.config = config
        self.browser_service = browser_service
        self.schedules = []
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        
        self.load_schedules()

    def load_schedules(self):
        """Load schedules from disk"""
        if os.path.exists(self.config.SCHEDULES_FILE):
            try:
                with open(self.config.SCHEDULES_FILE, 'r') as f:
                    self.schedules = json.load(f)
                logger.info(f"Loaded {len(self.schedules)} schedules")
            except Exception as e:
                logger.error(f"Error loading schedules: {e}")
                self.schedules = []
        else:
            self.schedules = []

    def save_schedules(self):
        """Save schedules to disk"""
        try:
            with open(self.config.SCHEDULES_FILE, 'w') as f:
                json.dump(self.schedules, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving schedules: {e}")

    def add_schedule(self, url, start_time, end_time, repeat=False, name=None):
        """Add a new schedule"""
        with self.lock:
            schedule = {
                'id': str(int(time.time() * 1000)),
                'url': url,
                'name': name or url,
                'start_time': start_time, # ISO format string
                'end_time': end_time,     # ISO format string
                'repeat': repeat,
                'status': 'pending',      # pending, active, completed, download_started
                'next_check': None,
                'last_check': None,
                'created_at': datetime.now().isoformat()
            }
            # Initialize next check
            self._update_next_check(schedule)
            
            self.schedules.append(schedule)
            self.save_schedules()
            return schedule

    def remove_schedule(self, schedule_id):
        """Remove a schedule"""
        with self.lock:
            self.schedules = [s for s in self.schedules if s['id'] != schedule_id]
            self.save_schedules()
            return True

    def get_schedules(self):
        """Get all schedules"""
        return self.schedules

    def start(self):
        """Start the scheduler loop"""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info("Scheduler started")

    def stop(self):
        """Stop the scheduler loop"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
            logger.info("Scheduler stopped")

    def _run_loop(self):
        """Main scheduler loop"""
        logger.info("Scheduler loop running")
        while self.running:
            try:
                self._check_schedules()
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")
            
            # Sleep for a bit before next iteration (e.g., 30 seconds)
            # We don't need super high precision
            for _ in range(30):
                if not self.running: 
                    break
                time.sleep(1)

    def _check_schedules(self):
        """Check all schedules and run tasks if needed"""
        now = datetime.now()
        
        with self.lock:
            for schedule in self.schedules:
                if schedule['status'] == 'completed':
                    continue

                try:
                    start_dt = datetime.fromisoformat(schedule['start_time'])
                    end_dt = datetime.fromisoformat(schedule['end_time'])
                    
                    # Check if window passed
                    if now > end_dt:
                        if schedule['repeat']:
                            # Move to next week
                            self._reschedule_next_week(schedule)
                        else:
                            if schedule['status'] != 'download_started':
                                schedule['status'] = 'completed'
                        continue

                    # Check if currently active window
                    if start_dt <= now <= end_dt:
                        if schedule['status'] == 'download_started':
                            # Already downloaded for this window
                            continue
                        
                        schedule['status'] = 'active'
                        
                        # Check if it's time to check stream
                        next_check = schedule.get('next_check')
                        if not next_check or now >= datetime.fromisoformat(next_check):
                            # It's time!
                            self._perform_check(schedule)
                    
                    elif now < start_dt:
                         schedule['status'] = 'pending'

                except Exception as e:
                    logger.error(f"Error processing schedule {schedule['id']}: {e}")
            
            self.save_schedules()

    def _update_next_check(self, schedule):
        """Calculate next random check time (7-11 mins from now)"""
        minutes = random.uniform(7, 11)
        next_dt = datetime.now() + timedelta(minutes=minutes)
        schedule['next_check'] = next_dt.isoformat()

    def _reschedule_next_week(self, schedule):
        """Move schedule to next week"""
        start_dt = datetime.fromisoformat(schedule['start_time'])
        end_dt = datetime.fromisoformat(schedule['end_time'])
        
        new_start = start_dt + timedelta(days=7)
        new_end = end_dt + timedelta(days=7)
        
        schedule['start_time'] = new_start.isoformat()
        schedule['end_time'] = new_end.isoformat()
        schedule['status'] = 'pending'
        schedule['next_check'] = None # Will be set when it becomes pending/active? 
        # Actually better to clear it so it resets when window approaches or enter
        
        logger.info(f"Rescheduled {schedule['id']} to next week: {new_start}")

    def _perform_check(self, schedule):
        """Perform the actual browser check"""
        logger.info(f"Performing scheduled check for {schedule['name']} ({schedule['url']})")
        
        # Determine duration (20-60s)
        duration = random.uniform(20, 60)
        
        # Thread logic for the check so we don't block main scheduler loop for a minute
        check_thread = threading.Thread(
            target=self._run_browser_check_task,
            args=(schedule, duration)
        )
        check_thread.start()
        
        # Update next check time immediately so we don't spawn multiple
        self._update_next_check(schedule)

    def _run_browser_check_task(self, schedule, duration):
        """The actual task running in a separate thread"""
        browser_id = f"sched_{schedule['id']}_{int(time.time())}"
        
        try:
            # Start browser
            logger.info(f"Opening browser for schedule {schedule['id']}")
            success, detector = self.browser_service.start_browser(
                url=schedule['url'],
                browser_id=browser_id,
                auto_download=True, # Important!
                filename=None # Auto name
            )
            
            if not success:
                logger.warning(f"Failed to start browser for schedule {schedule['id']}")
                return

            # Wait for random duration or until download starts
            start_wait = time.time()
            while time.time() - start_wait < duration:
                # Check status
                status = self.browser_service.get_browser_status(browser_id)
                if not status:
                    break
                
                # Check if downloading
                # BrowserService.get_browser_status returns keys like 'started', 'finding_stream', etc.
                # If auto_download is True, it might have transitioned to download service.
                # We need to check if a download was triggered. 
                # The detector has `set_download_callback`.
                
                # If download started, the detector might be closed or status changed?
                # Actually, `start_browser` in `browser_service.py` sets callback `self.download_service.start_download`.
                # If download starts, `start_download` is called.
                
                # We can check `download_service` status for this browser_id?
                # Or check `detector.get_status()`?
                
                # Let's check if we can detect if download started.
                # In `detector.py` (not visible but inferred), likely it calls callback.
                
                # We can rely on `download_service.get_download_status(browser_id)`
                dl_status = self.browser_service.download_service.get_download_status(browser_id)
                if dl_status:
                    logger.info(f"Download started for schedule {schedule['id']}!")
                    
                    with self.lock:
                        # Re-fetch schedule to ensure we have latest state (though it's in mem)
                        # We need to find the specific dict object in self.schedules
                        # (since we are in a thread, self.schedules might have changed if reloaded, but we share reference)
                         for s in self.schedules:
                             if s['id'] == schedule['id']:
                                 s['status'] = 'download_started'
                                 self.save_schedules()
                                 break
                    
                    # We can close browser if we want, or let it handle it.
                    # Usually download detached from browser? 
                    # If ffmpeg, browser can close. If direct, browser can close.
                    # The `auto_download` logic in `detector` likely closes browser if stream found?
                    # Let's assume we should close it if it's still open to be safe, 
                    # BUT `download_service` might be using cookies from it?
                    # `BrowserService.start_browser` closes existing browsers.
                    
                    # If download started, we are GOOD.
                    # The loop will end.
                    break
                
                time.sleep(1)
            
            # cleanup
            logger.info(f"Closing browser for schedule {schedule['id']}")
            self.browser_service.close_browser(browser_id)

        except Exception as e:
            logger.error(f"Error in browser check task: {e}")
            try:
                self.browser_service.close_browser(browser_id)
            except:
                pass
