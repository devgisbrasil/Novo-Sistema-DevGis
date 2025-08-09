from flask import Flask, redirect, url_for, request
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_bcrypt import Bcrypt
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from flask_admin import AdminIndexView
from wtforms import PasswordField
import os
from datetime import datetime
import time
from sqlalchemy.exc import OperationalError, ProgrammingError

# Global extensions

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
bcrypt = Bcrypt()
admin = Admin(name="Admin", template_mode="bootstrap4")


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
    from .models import User, Role, UserRole, AccessLog  # noqa: F401

    # Ensure DB is ready; create tables and seed default roles with retries (handles Postgres startup lag)
    with app.app_context():
        attempts = 0
        max_attempts = int(os.getenv("DB_INIT_MAX_ATTEMPTS", 20))
        delay = float(os.getenv("DB_INIT_DELAY_SECONDS", 1.5))
        while attempts < max_attempts:
            try:
                # Simple connectivity check
                db.session.execute(db.text("SELECT 1"))
                db.create_all()
                # seed default admin role if not exists
                if not Role.query.filter_by(name="admin").first():
                    db.session.add(Role(name="admin"))
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

    # Access log for every request
    @app.before_request
    def log_access():
        # Avoid logging static and admin assets excessively
        ignored_prefixes = ("/static", "/favicon.ico")
        if request.path.startswith(ignored_prefixes):
            return
        try:
            user_id = current_user.get_id() if current_user.is_authenticated else None
            log = AccessLog(
                user_id=user_id,
                path=request.path,
                method=request.method,
                ip=request.headers.get("X-Forwarded-For", request.remote_addr),
                timestamp=datetime.utcnow(),
            )
            db.session.add(log)
            db.session.commit()
        except Exception:
            db.session.rollback()

    # Blueprints
    from .auth import auth_bp
    from .views import main_bp
    from .sig import sig_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(sig_bp)

    # Flask-Admin configuration with role-based access
    class AdminHomeView(AdminIndexView):
        def is_accessible(self):
            return current_user.is_authenticated and current_user.has_role("admin")

        def inaccessible_callback(self, name, **kwargs):
            return redirect(url_for("auth.login", next=request.url))

    class SecureModelView(ModelView):
        def is_accessible(self):
            return current_user.is_authenticated and current_user.has_role("admin")

        def inaccessible_callback(self, name, **kwargs):
            return redirect(url_for("auth.login", next=request.url))

    class UserModelView(SecureModelView):
        # oculta hash e usa campo de senha próprio
        form_excluded_columns = ("password_hash",)
        form_extra_fields = {
            "password": PasswordField("Senha (deixe em branco para não alterar)"),
        }

        column_searchable_list = ("name", "email")
        column_filters = ("active",)

        def on_model_change(self, form, model, is_created):
            # define/atualiza a senha se fornecida
            pwd = form.password.data if hasattr(form, "password") else None
            if pwd:
                model.set_password(pwd)
            return super().on_model_change(form, model, is_created)

    # Recreate admin with protected index view
    admin = Admin(
        app,
        name="Admin",
        template_mode="bootstrap4",
        index_view=AdminHomeView(),
        base_template="admin/master.html",
    )
    admin.add_view(UserModelView(User, db.session, category="Gerenciamento", endpoint="user"))
    admin.add_view(SecureModelView(Role, db.session, category="Gerenciamento", endpoint="role"))
    admin.add_view(SecureModelView(UserRole, db.session, category="Gerenciamento", endpoint="userrole"))
    admin.add_view(SecureModelView(AccessLog, db.session, category="Logs", endpoint="accesslog"))
    from .models import GeoJSONFile  # noqa: WPS433
    admin.add_view(SecureModelView(GeoJSONFile, db.session, category="SIG", endpoint="geojsonfile"))

    @app.route("/admin")
    def admin_root():
        return redirect("/admin/")

    return app
