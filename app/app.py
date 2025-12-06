from flask import Flask, render_template
from app.config import Config
from app.services import DownloadService, BrowserService
from app.routes import init_browser_routes, init_download_routes, add_clear_cookies_route, add_test_chrome_route


def create_app():
    """Application factory pattern"""
    # Initialize Flask app
    flask_app = Flask(__name__)

    # Load configuration
    config = Config()
    logger = config.setup_logging()
    config.check_directories()
    config.log_startup_info(logger)

    # Initialize services
    download_service = DownloadService(config.DOWNLOAD_DIR)
    browser_service = BrowserService(config, download_service)

    # Check Chrome installation at startup
    browser_service.check_chrome_installation()

    # Initialize and register routes
    browser_bp = init_browser_routes(browser_service, download_service)
    download_bp = init_download_routes(download_service, config.DOWNLOAD_DIR)

    # Add additional routes
    add_clear_cookies_route(browser_bp, browser_service)
    add_test_chrome_route(browser_bp, config)

    # Register blueprints
    flask_app.register_blueprint(browser_bp)
    flask_app.register_blueprint(download_bp)

    # Main route
    @flask_app.route('/')
    def index():
        """Main page"""
        return render_template('index.html')

    # Store services in app context for access if needed
    flask_app.config['browser_service'] = browser_service
    flask_app.config['download_service'] = download_service
    flask_app.config['app_config'] = config

    logger.info("=" * 80)
    logger.info("Application initialized successfully")
    logger.info("=" * 80)

    return flask_app


if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=False)
