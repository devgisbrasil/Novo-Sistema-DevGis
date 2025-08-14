from flask import Flask, redirect, url_for, request, render_template, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_bcrypt import Bcrypt
from wtforms import SelectMultipleField
from wtforms import PasswordField, SelectMultipleField, widgets

import os
from datetime import datetime, timedelta
import time
from sqlalchemy import func, and_, or_
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import joinedload

# Global extensions

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
bcrypt = Bcrypt()
admin = None


def create_app():
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "SQLALCHEMY_DATABASE_URI",
        "sqlite:///devgis.db",
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    bcrypt.init_app(app)
    login_manager.login_view = "auth.login"

    # Import models after db
    from .models import User  # noqa: F401

    # Ensure DB is ready; create tables with retries (handles Postgres startup lag)
    with app.app_context():
        attempts = 0
        max_attempts = int(os.getenv("DB_INIT_MAX_ATTEMPTS", 20))
        delay = float(os.getenv("DB_INIT_DELAY_SECONDS", 1.5))
        while attempts < max_attempts:
            try:
                # Simple connectivity check
                db.session.execute(db.text("SELECT 1"))
                db.create_all()
                db.session.commit()
                break

            except (OperationalError, ProgrammingError):
                db.session.rollback()
                attempts += 1
                time.sleep(delay)
            except Exception:
                db.session.rollback()
                attempts += 1
                time.sleep(delay)

    # Blueprints
    from .auth import auth_bp
    from .views import main_bp
    from .sig import sig_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(sig_bp)

    return app
