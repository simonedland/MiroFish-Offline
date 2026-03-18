"""
MiroFish Backend - Flask Application Factory
"""

import os
import time
import warnings

# Suppress multiprocessing resource_tracker warnings (from third-party libraries like transformers)
# Must be set before all other imports
warnings.filterwarnings("ignore", message=".*resource_tracker.*")

from flask import Flask, request
from flask_cors import CORS

from .config import Config
from .utils.logger import setup_logger, get_logger


def _init_neo4j_storage(logger, should_log_startup):
    """Initialize Neo4j storage with retries to tolerate container startup lag."""
    from .storage import Neo4jStorage

    timeout_seconds = int(os.environ.get('NEO4J_INIT_TIMEOUT', '90'))
    retry_interval = int(os.environ.get('NEO4J_INIT_RETRY_INTERVAL', '3'))
    deadline = time.time() + timeout_seconds
    attempt = 1
    last_error = None

    while time.time() < deadline:
        try:
            storage = Neo4jStorage()
            if should_log_startup:
                logger.info("Neo4jStorage initialized (connected to %s)", Config.NEO4J_URI)
            return storage
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Neo4jStorage initialization attempt %s failed: %s",
                attempt,
                exc,
            )
            attempt += 1
            time.sleep(retry_interval)

    logger.error(
        "Neo4jStorage initialization failed after %ss: %s",
        timeout_seconds,
        last_error,
    )
    return None


def create_app(config_class=Config):
    """Flask application factory function"""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Configure JSON encoding: ensure Chinese displays directly (not as \uXXXX)
    # Flask >= 2.3 uses app.json.ensure_ascii, older versions use JSON_AS_ASCII config
    if hasattr(app, 'json') and hasattr(app.json, 'ensure_ascii'):
        app.json.ensure_ascii = False

    # Setup logging
    logger = setup_logger('mirofish')

    # Only print startup info in reloader subprocess (avoid printing twice in debug mode)
    is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    debug_mode = app.config.get('DEBUG', False)
    should_log_startup = not debug_mode or is_reloader_process

    if should_log_startup:
        logger.info("=" * 50)
        logger.info("MiroFish-Offline Backend starting...")
        logger.info("=" * 50)

    # Enable CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # --- Initialize Neo4jStorage singleton (DI via app.extensions) ---
    app.extensions['neo4j_storage'] = _init_neo4j_storage(logger, should_log_startup)

    # Register simulation process cleanup function (ensure all simulation processes terminate on server shutdown)
    from .services.simulation_runner import SimulationRunner
    SimulationRunner.register_cleanup()
    if should_log_startup:
        logger.info("Simulation process cleanup function registered")

    # Request logging middleware
    @app.before_request
    def log_request():
        logger = get_logger('mirofish.request')
        logger.debug(f"Request: {request.method} {request.path}")
        if request.content_type and 'json' in request.content_type:
            logger.debug(f"Request body: {request.get_json(silent=True)}")

    @app.after_request
    def log_response(response):
        logger = get_logger('mirofish.request')
        logger.debug(f"Response: {response.status_code}")
        return response

    # Register blueprints
    from .api import graph_bp, simulation_bp, report_bp
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')

    # Health check
    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'MiroFish-Offline Backend'}

    if should_log_startup:
        logger.info("MiroFish-Offline Backend startup complete")

    return app

