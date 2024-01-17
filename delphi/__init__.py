import logging
import os
from logging.handlers import RotatingFileHandler

from flask import Flask
from flask_apscheduler import APScheduler
from flask_login import LoginManager
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy

# Instantiate extensions with default configuration
scheduler = APScheduler()
login_manager = LoginManager()
session = Session()
db = SQLAlchemy()


# Factory function to create Flask app, load config class and attach extensions
def create_app(config_class) -> Flask:
    app = Flask(__name__)

    # Load configuration from config class
    app.config.from_object(config_class)

    # Initialize extensions within the Flask app context with config options
    db.init_app(app)
    scheduler.init_app(app)
    login_manager.init_app(app)
    session.init_app(app)

    # Init logger
    logger_init(app)

    # Create db tables if empty
    create_tables(app)

    # Registering blueprints
    from delphi.oauth.views import oauth

    app.register_blueprint(oauth)

    # Login manager setup
    @login_manager.user_loader
    def load_user(request_id):
        from delphi.oauth.models import Token

        return Token.get_by_request(request_id)

    # Start the scheduler thread
    scheduler.start()
    app.logger.info("APScheduler started successfully.")

    app.logger.info("App created successfully.")
    return app


# Factory function to create tables at database when initializing Flask app
def create_tables(app) -> None:
    """
    Importing the models with SQLAlchemy superclasses and calling create_all will:

    - Call db SQLAlchemy's instance to scan for imported models with SQLAlchemy superclasses.
    - Create the tables if they don't exist, using models' defined structure.
    """
    from delphi.oauth.models import Token, TokenRefreshJob

    with app.app_context():
        db.create_all()


# Factory function to initialize logger
def logger_init(app) -> None:
    # Logging setup
    if not app.debug:
        if not os.path.exists("logs"):
            os.mkdir("logs")
        file_handler = RotatingFileHandler("logs/app.log", maxBytes=10240, backupCount=30)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]")
        )
        file_handler.setLevel(logging.DEBUG)
        app.logger.addHandler(file_handler)

        app.logger.setLevel(logging.DEBUG)
        app.logger.info("Your app logger is ready")
