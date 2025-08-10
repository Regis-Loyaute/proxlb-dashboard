from flask import Flask
from .config import load_settings, configure_ssl_warnings

def create_app() -> Flask:
    settings = load_settings()
    configure_ssl_warnings(settings.VERIFY_SSL)

    app = Flask(__name__)
    app.secret_key = settings.FLASK_SECRET

    # attach settings on app for easy access
    app.config["SETTINGS"] = settings

    # register blueprints
    from .routes.dashboard import bp as dashboard_bp
    from .routes.api import bp as api_bp
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    return app
