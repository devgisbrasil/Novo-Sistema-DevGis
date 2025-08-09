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

    roles = relationship("Role", secondary="user_roles", back_populates="users")

    def set_password(self, password: str):
        self.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

    def check_password(self, password: str) -> bool:
        return bcrypt.check_password_hash(self.password_hash, password)

    def has_role(self, role_name: str) -> bool:
        return any(r.name == role_name for r in self.roles)

    def __repr__(self):
        return f"<User {self.email}>"


class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)

    users = relationship("User", secondary="user_roles", back_populates="roles")

    def __repr__(self):
        return f"<Role {self.name}>"


class UserRole(db.Model):
    __tablename__ = "user_roles"
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), primary_key=True)


class AccessLog(db.Model):
    __tablename__ = "access_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    path = db.Column(db.String(512), nullable=False)
    method = db.Column(db.String(10), nullable=False)
    ip = db.Column(db.String(64), nullable=True)
    timestamp = db.Column(db.DateTime, server_default=func.now(), nullable=False)


@login_manager.user_loader
def load_user(user_id: str):
    return User.query.get(int(user_id))
