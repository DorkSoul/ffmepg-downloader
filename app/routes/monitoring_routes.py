from flask import Blueprint, jsonify, request

def init_monitoring_routes(monitoring_service):
    """Initialize monitoring routes with service"""
    monitoring_bp = Blueprint('monitoring', __name__)

    @monitoring_bp.route('/api/monitoring/streams', methods=['GET'])
    def get_streams():
        """Get all monitored streams"""
        streams = monitoring_service.get_streams()
        return jsonify({'streams': streams})

    @monitoring_bp.route('/api/monitoring/streams', methods=['POST'])
    def add_stream():
        """Add a new stream to monitor"""
        data = request.get_json()
        url = data.get('url')
        name = data.get('name')

        if not url:
            return jsonify({'success': False, 'error': 'URL is required'}), 400

        try:
            stream = monitoring_service.add_stream(url, name)
            return jsonify({'success': True, 'stream': stream})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @monitoring_bp.route('/api/monitoring/streams/<stream_id>', methods=['DELETE'])
    def remove_stream(stream_id):
        """Remove a monitored stream"""
        if monitoring_service.remove_stream(stream_id):
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Stream not found'}), 404

    return monitoring_bp
