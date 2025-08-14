from flask_login import UserMixin
from . import db, login_manager, bcrypt
from sqlalchemy.orm import relationship
from sqlalchemy import func


class User(db.Model, UserMixin):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean, default=True)


    def set_password(self, password: str):
        self.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

    def check_password(self, password: str) -> bool:
        return bcrypt.check_password_hash(self.password_hash, password)

    # No roles/permissions: everyone has full access once authenticated
    def has_role(self, role_name: str) -> bool:  # kept for compatibility in templates
        return False

    def __repr__(self):
        return f"<User {self.email}>"


class SavedMap(db.Model):
    __tablename__ = "saved_maps"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    data = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, server_default=func.now(), nullable=False)
    public_token = db.Column(db.String(64), unique=True, nullable=True)

    user = relationship("User")

    def __repr__(self):
        return f"<SavedMap {self.id} {self.name}>"




class GeoJSONFile(db.Model):
    __tablename__ = "geojson_files"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    data = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, server_default=func.now(), nullable=False)

    user = relationship("User")


@login_manager.user_loader
def load_user(user_id: str):
    return User.query.get(int(user_id))
