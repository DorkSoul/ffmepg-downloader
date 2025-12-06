import os
import time
import logging
import subprocess
import threading
from app.utils import MetadataExtractor, ThumbnailGenerator

logger = logging.getLogger(__name__)


class DownloadService:
    """Manages video downloads using FFmpeg"""

    def __init__(self, download_dir):
        self.download_dir = download_dir
        self.download_queue = {}
        self.direct_download_status = {}
        self.download_thumbnails = {}  # Cache for thumbnails

    def start_download(self, browser_id, stream_url, filename, resolution_name, stream_metadata=None):
        """Start a download using FFmpeg"""
        output_path = os.path.join(self.download_dir, filename)

        # Start download in background thread
        threading.Thread(
            target=self._process_download,
            args=(browser_id, stream_url, output_path, resolution_name, stream_metadata),
            daemon=True
        ).start()

        return output_path

    def start_direct_download(self, browser_id, stream_url, filename):
        """Start a direct download with metadata enrichment"""
        output_path = os.path.join(self.download_dir, filename)

        threading.Thread(
            target=self._direct_download,
            args=(browser_id, stream_url, output_path),
            daemon=True
        ).start()

        return browser_id, output_path

    def _process_download(self, browser_id, stream_url, output_path, resolution_name, stream_metadata=None):
        """Process download in background thread"""
        try:
            logger.info(f"Starting FFmpeg download: {stream_url} -> {output_path}")

            # Get metadata for display
            if stream_metadata:
                resolution_display = stream_metadata.get('resolution') or stream_metadata.get('name', 'Unknown')
                if stream_metadata.get('resolution') and 'x' in str(stream_metadata.get('resolution')):
                    fps = stream_metadata.get('framerate', '').split('.')[0] if stream_metadata.get('framerate') else ''
                    resolution_display = f"{stream_metadata.get('resolution')}@{fps}fps" if fps else stream_metadata.get('resolution')
                elif stream_metadata.get('name'):
                    resolution_display = stream_metadata.get('name')
                metadata = stream_metadata
            else:
                resolution_display = 'Unknown'
                metadata = {}

            # Start FFmpeg process
            process = self._start_ffmpeg_process(stream_url, output_path)

            # Store process info
            self.download_queue[browser_id] = {
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

            # Wait for completion
            stdout, stderr = process.communicate()

            # Mark as completed
            if browser_id in self.download_queue:
                self.download_queue[browser_id]['completed_at'] = time.time()
                self.download_queue[browser_id]['success'] = (process.returncode == 0)

            if process.returncode == 0:
                logger.info(f"Download completed: {output_path}")
            else:
                logger.error(f"FFmpeg error: {stderr}")

        except Exception as e:
            logger.error(f"Download failed: {e}")
            if browser_id in self.download_queue:
                self.download_queue[browser_id]['completed_at'] = time.time()
                self.download_queue[browser_id]['success'] = False

    def _direct_download(self, browser_id, stream_url, output_path):
        """Execute direct download with metadata enrichment"""
        try:
            logger.info(f"Starting direct download: {stream_url[:100]}...")

            # Create stream entry for metadata enrichment
            stream_entry = {
                'url': stream_url,
                'bandwidth': 0,
                'resolution': '',
                'framerate': '',
                'codecs': '',
                'name': 'direct'
            }

            # Enrich metadata
            logger.info("Enriching stream metadata for direct download...")
            MetadataExtractor.enrich_stream_metadata(stream_entry)

            # Generate thumbnail
            logger.info("Generating thumbnail for direct download...")
            thumbnail = ThumbnailGenerator.generate_stream_thumbnail(stream_url)

            # Prepare metadata
            resolution_display = stream_entry.get('resolution', 'Unknown')
            if stream_entry.get('resolution') and 'x' in str(stream_entry.get('resolution')):
                fps = stream_entry.get('framerate', '').split('.')[0] if stream_entry.get('framerate') else ''
                resolution_display = f"{stream_entry.get('resolution')}@{fps}fps" if fps else stream_entry.get('resolution')

            # Store status
            self.direct_download_status[browser_id] = {
                'browser_id': browser_id,
                'is_running': True,
                'download_started': True,
                'thumbnail': thumbnail.split(',', 1)[1] if thumbnail and thumbnail.startswith('data:image/') else thumbnail,
                'selected_stream_metadata': stream_entry
            }

            # Start FFmpeg
            process = self._start_ffmpeg_process(stream_url, output_path)

            # Store in queue
            self.download_queue[browser_id] = {
                'process': process,
                'output_path': output_path,
                'stream_url': stream_url,
                'started_at': time.time(),
                'resolution_name': resolution_display,
                'resolution': stream_entry.get('resolution', 'Unknown'),
                'framerate': stream_entry.get('framerate', 'Unknown'),
                'codecs': stream_entry.get('codecs', 'Unknown'),
                'filename': os.path.basename(output_path)
            }

            stdout, stderr = process.communicate()

            # Mark as completed
            if browser_id in self.download_queue:
                self.download_queue[browser_id]['completed_at'] = time.time()
                self.download_queue[browser_id]['success'] = (process.returncode == 0)

            if process.returncode == 0:
                logger.info(f"Direct download completed: {output_path}")
            else:
                logger.error(f"Direct download failed: {stderr}")

            # Clean up status
            if browser_id in self.direct_download_status:
                del self.direct_download_status[browser_id]

        except Exception as e:
            logger.error(f"Direct download error: {e}")
            if browser_id in self.download_queue:
                self.download_queue[browser_id]['completed_at'] = time.time()
                self.download_queue[browser_id]['success'] = False

    def _start_ffmpeg_process(self, stream_url, output_path):
        """Start FFmpeg process for downloading"""
        cmd = [
            'ffmpeg',
            '-i', stream_url,
            '-c', 'copy',
            '-bsf:a', 'aac_adtstoasc',
            '-y',  # Overwrite output file
            output_path
        ]

        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )

    def get_active_downloads(self):
        """Get list of active downloads with progress"""
        active = []

        for browser_id, download_info in list(self.download_queue.items()):
            process = download_info.get('process')
            output_path = download_info.get('output_path')
            started_at = download_info.get('started_at')

            # Check file size
            file_size = 0
            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path)

            # Calculate duration
            duration = int(time.time() - started_at)

            # Check if process is still running
            is_running = process.poll() is None if process else False

            # Extract thumbnail
            thumbnail = None
            if is_running and output_path:
                thumbnail = ThumbnailGenerator.extract_thumbnail_from_file(
                    output_path, self.download_thumbnails, browser_id
                )

            active.append({
                'browser_id': browser_id,
                'filename': download_info.get('filename', 'Unknown'),
                'resolution': download_info.get('resolution_name', 'Unknown'),
                'resolution_detail': download_info.get('resolution', 'Unknown'),
                'framerate': download_info.get('framerate', 'Unknown'),
                'codecs': download_info.get('codecs', 'Unknown'),
                'size': file_size,
                'duration': duration,
                'is_running': is_running,
                'thumbnail': thumbnail
            })

        return active

    def stop_download(self, browser_id):
        """Stop an active download"""
        if browser_id in self.download_queue:
            download_info = self.download_queue[browser_id]
            process = download_info.get('process')

            if process and process.poll() is None:
                logger.info(f"Stopping download for browser {browser_id}")
                process.terminate()
                process.wait(timeout=5)
                logger.info(f"Download stopped for browser {browser_id}")

            del self.download_queue[browser_id]
            return True
        return False

    def get_download_status(self, browser_id):
        """Get download status for a specific browser_id"""
        if browser_id in self.download_queue:
            download_info = self.download_queue[browser_id]
            # Calculate duration
            if 'completed_at' in download_info:
                duration = download_info['completed_at'] - download_info['started_at']
            else:
                duration = time.time() - download_info['started_at']

            return {
                'output_path': download_info['output_path'],
                'stream_url': download_info['stream_url'],
                'duration': duration,
                'completed': 'completed_at' in download_info,
                'success': download_info.get('success', True)
            }
        return None
