from flask import Flask, render_template, request, jsonify, send_file
import os
import subprocess
import json
import time
import threading
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from pathlib import Path
import requests

app = Flask(__name__)

# Configuration
DOWNLOAD_PATH = os.getenv('DOWNLOAD_PATH', '/downloads')
CHROME_TIMEOUT = int(os.getenv('CHROME_TIMEOUT', 15))
DEFAULT_QUALITY = os.getenv('DEFAULT_QUALITY', '1080')

# Global variables to track active downloads and Chrome sessions
active_sessions = {}
download_status = {}

class ChromeStreamDetector:
    def __init__(self, url, session_id):
        self.url = url
        self.session_id = session_id
        self.driver = None
        self.detected_streams = []
        self.download_started = False
        
    def setup_chrome(self):
        """Setup Chrome with remote debugging and proper options"""
        chrome_options = Options()
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--remote-debugging-port=9222')
        chrome_options.add_argument('--user-data-dir=/home/appuser/.config/google-chrome')
        chrome_options.add_experimental_option('perfLoggingPrefs', {
            'enableNetwork': True,
            'enablePage': False,
        })
        chrome_options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
        
        service = Service('/usr/bin/chromedriver')
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        
    def monitor_network(self):
        """Monitor Chrome network traffic for video streams"""
        video_extensions = ['.m3u8', '.mpd', '.mp4', '.m4s', '.ts']
        video_types = ['video/', 'application/vnd.apple.mpegurl', 'application/dash+xml']
        
        while not self.download_started:
            try:
                logs = self.driver.get_log('performance')
                
                for entry in logs:
                    log = json.loads(entry['message'])['message']
                    
                    if log.get('method') == 'Network.responseReceived':
                        response = log.get('params', {}).get('response', {})
                        url = response.get('url', '')
                        mime_type = response.get('mimeType', '')
                        
                        # Check if this is a video stream
                        is_video = any(ext in url.lower() for ext in video_extensions)
                        is_video_mime = any(vtype in mime_type for vtype in video_types)
                        
                        if is_video or is_video_mime:
                            if url not in self.detected_streams:
                                self.detected_streams.append(url)
                                print(f"Detected stream: {url}")
                                
                                # Start download for the first valid stream
                                if self.should_download(url):
                                    self.start_download(url)
                                    return
                
                time.sleep(0.5)
            except Exception as e:
                print(f"Error monitoring network: {e}")
                time.sleep(1)
    
    def should_download(self, url):
        """Determine if this stream should be downloaded"""
        # Prioritize m3u8 and mpd streams
        if '.m3u8' in url.lower() or '.mpd' in url.lower():
            return True
        # Also accept direct mp4 files
        if '.mp4' in url.lower() and 'manifest' not in url.lower():
            return True
        return False
    
    def start_download(self, stream_url):
        """Start FFmpeg download and generate thumbnail"""
        self.download_started = True
        
        # Generate filename
        timestamp = int(time.time())
        filename = f"video_{timestamp}.mp4"
        output_path = os.path.join(DOWNLOAD_PATH, filename)
        
        # Update session status
        active_sessions[self.session_id]['stream_url'] = stream_url
        active_sessions[self.session_id]['filename'] = filename
        active_sessions[self.session_id]['status'] = 'downloading'
        
        # Start thumbnail generation in background
        threading.Thread(target=self.generate_thumbnail, args=(stream_url,)).start()
        
        # Start FFmpeg download
        threading.Thread(target=self.run_ffmpeg, args=(stream_url, output_path)).start()
    
    def generate_thumbnail(self, stream_url):
        """Generate thumbnail from stream"""
        try:
            thumbnail_path = os.path.join('/app/static', f'thumb_{self.session_id}.jpg')
            cmd = [
                'ffmpeg',
                '-i', stream_url,
                '-ss', '00:00:03',
                '-vframes', '1',
                '-q:v', '2',
                thumbnail_path,
                '-y'
            ]
            subprocess.run(cmd, capture_output=True, timeout=30)
            active_sessions[self.session_id]['thumbnail'] = f'thumb_{self.session_id}.jpg'
        except Exception as e:
            print(f"Error generating thumbnail: {e}")
    
    def run_ffmpeg(self, stream_url, output_path):
        """Run FFmpeg to download the stream"""
        try:
            cmd = [
                'ffmpeg',
                '-i', stream_url,
                '-c', 'copy',
                '-bsf:a', 'aac_adtstoasc',
                output_path,
                '-y'
            ]
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            
            # Monitor progress
            for line in process.stderr:
                if 'time=' in line:
                    # Update progress if needed
                    pass
            
            process.wait()
            
            if process.returncode == 0:
                active_sessions[self.session_id]['status'] = 'completed'
            else:
                active_sessions[self.session_id]['status'] = 'failed'
                active_sessions[self.session_id]['error'] = 'FFmpeg download failed'
                
        except Exception as e:
            active_sessions[self.session_id]['status'] = 'failed'
            active_sessions[self.session_id]['error'] = str(e)
    
    def run(self):
        """Main method to run the detector"""
        try:
            self.setup_chrome()
            self.driver.get(self.url)
            
            # Start monitoring in background
            monitor_thread = threading.Thread(target=self.monitor_network)
            monitor_thread.start()
            
            # Wait for user interaction or stream detection
            monitor_thread.join(timeout=300)  # 5 minute timeout
            
            # Keep Chrome open for CHROME_TIMEOUT seconds after download starts
            if self.download_started:
                time.sleep(CHROME_TIMEOUT)
            
        except Exception as e:
            active_sessions[self.session_id]['status'] = 'failed'
            active_sessions[self.session_id]['error'] = str(e)
        finally:
            if self.driver:
                self.driver.quit()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/direct-download', methods=['POST'])
def direct_download():
    """Handle direct video URL downloads"""
    data = request.json
    video_url = data.get('url')
    quality = data.get('quality', DEFAULT_QUALITY)
    
    if not video_url:
        return jsonify({'error': 'No URL provided'}), 400
    
    # Generate session ID
    session_id = f"direct_{int(time.time())}"
    
    # Start download
    active_sessions[session_id] = {
        'type': 'direct',
        'url': video_url,
        'status': 'starting',
        'filename': None
    }
    
    # Run FFmpeg download in background
    threading.Thread(
        target=download_direct,
        args=(video_url, session_id, quality)
    ).start()
    
    return jsonify({'session_id': session_id})

@app.route('/api/browser-download', methods=['POST'])
def browser_download():
    """Handle browser-based downloads with Chrome"""
    data = request.json
    page_url = data.get('url')
    
    if not page_url:
        return jsonify({'error': 'No URL provided'}), 400
    
    # Generate session ID
    session_id = f"browser_{int(time.time())}"
    
    # Initialize session
    active_sessions[session_id] = {
        'type': 'browser',
        'url': page_url,
        'status': 'opening_browser',
        'filename': None,
        'thumbnail': None
    }
    
    # Start Chrome detector in background
    detector = ChromeStreamDetector(page_url, session_id)
    threading.Thread(target=detector.run).start()
    
    return jsonify({
        'session_id': session_id,
        'vnc_url': 'http://localhost:6080/vnc.html'
    })

@app.route('/api/status/<session_id>')
def get_status(session_id):
    """Get status of a download session"""
    if session_id not in active_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    return jsonify(active_sessions[session_id])

@app.route('/api/close-browser/<session_id>', methods=['POST'])
def close_browser(session_id):
    """Manually close browser for a session"""
    if session_id in active_sessions:
        active_sessions[session_id]['manual_close'] = True
    return jsonify({'success': True})

def download_direct(video_url, session_id, quality):
    """Download video directly with FFmpeg"""
    try:
        timestamp = int(time.time())
        filename = f"video_{timestamp}.mp4"
        output_path = os.path.join(DOWNLOAD_PATH, filename)
        
        active_sessions[session_id]['filename'] = filename
        active_sessions[session_id]['status'] = 'downloading'
        
        cmd = [
            'ffmpeg',
            '-i', video_url,
            '-c', 'copy',
            '-bsf:a', 'aac_adtstoasc',
            output_path,
            '-y'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            active_sessions[session_id]['status'] = 'completed'
        else:
            active_sessions[session_id]['status'] = 'failed'
            active_sessions[session_id]['error'] = result.stderr
            
    except Exception as e:
        active_sessions[session_id]['status'] = 'failed'
        active_sessions[session_id]['error'] = str(e)

if __name__ == '__main__':
    # Ensure download directory exists
    os.makedirs(DOWNLOAD_PATH, exist_ok=True)
    app.run(host='0.0.0.0', port=5000, debug=False)
