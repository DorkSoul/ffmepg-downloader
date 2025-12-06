import os
import time
import logging
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)

download_bp = Blueprint('download', __name__, url_prefix='/api/downloads')


def init_download_routes(download_service, download_dir):
    """Initialize download routes with services"""

    @download_bp.route('/direct', methods=['POST'])
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

            # Start download
            browser_id, output_path = download_service.start_direct_download(
                f"direct_{timestamp}",
                stream_url,
                filename
            )

            return jsonify({
                'success': True,
                'browser_id': browser_id,
                'message': 'Download started',
                'output_path': output_path
            })

        except Exception as e:
            logger.error(f"Direct download error: {e}")
            return jsonify({'error': str(e)}), 500

    @download_bp.route('/list', methods=['GET'])
    def list_downloads():
        """List all downloads"""
        try:
            downloads = []

            # List completed downloads
            if os.path.exists(download_dir):
                for filename in os.listdir(download_dir):
                    filepath = os.path.join(download_dir, filename)
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

    @download_bp.route('/active', methods=['GET'])
    def active_downloads():
        """Get active downloads with progress"""
        try:
            active = download_service.get_active_downloads()
            return jsonify({'active_downloads': active})

        except Exception as e:
            logger.error(f"Active downloads error: {e}")
            return jsonify({'error': str(e)}), 500

    @download_bp.route('/check-filename', methods=['GET'])
    def check_filename():
        """Check if a filename already exists in the download directory"""
        try:
            filename = request.args.get('filename', '')
            if not filename:
                return jsonify({'exists': False})
            
            filepath = os.path.join(download_dir, filename)
            exists = os.path.exists(filepath)
            
            return jsonify({'exists': exists, 'filename': filename})
        except Exception as e:
            logger.error(f"Check filename error: {e}")
            return jsonify({'exists': False, 'error': str(e)})

    @download_bp.route('/stop/<browser_id>', methods=['POST'])
    def stop_download(browser_id):
        """Stop an active download"""
        try:
            if download_service.stop_download(browser_id):
                return jsonify({'success': True, 'message': 'Download stopped'})
            else:
                return jsonify({'error': 'Download not found'}), 404

        except Exception as e:
            logger.error(f"Stop download error: {e}")
            return jsonify({'error': str(e)}), 500

    return download_bp
