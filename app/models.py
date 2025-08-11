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


class Permission(db.Model):
    __tablename__ = "permissions"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    description = db.Column(db.String(255))
    
    def __repr__(self):
        return f"<Permission {self.name}>"


class RolePermission(db.Model):
    __tablename__ = "role_permissions"
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), primary_key=True)
    permission_id = db.Column(db.Integer, db.ForeignKey("permissions.id"), primary_key=True)
    
    role = relationship("Role", back_populates="role_permissions")
    permission = relationship("Permission")


class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, server_default=func.now(), nullable=False)
    updated_at = db.Column(db.DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    users = relationship("User", secondary="user_roles", back_populates="roles")
    role_permissions = relationship("RolePermission", back_populates="role")
    
    def has_permission(self, permission_name):
        return any(rp.permission.name == permission_name for rp in self.role_permissions)
    
    def add_permission(self, permission_name):
        if not self.has_permission(permission_name):
            permission = Permission.query.filter_by(name=permission_name).first()
            if permission:
                role_permission = RolePermission(role_id=self.id, permission_id=permission.id)
                db.session.add(role_permission)
    
    def remove_permission(self, permission_name):
        for rp in self.role_permissions:
            if rp.permission.name == permission_name:
                db.session.delete(rp)
    
    def get_permissions(self):
        return [rp.permission.name for rp in self.role_permissions]

    def __repr__(self):
        return f"<Role {self.name}>"


class UserRole(db.Model):
    __tablename__ = "user_roles"
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), primary_key=True)
    assigned_at = db.Column(db.DateTime, server_default=func.now(), nullable=False)
    
    user = relationship("User", backref="user_roles")
    role = relationship("Role", backref="user_roles")
    
    def __repr__(self):
        return f"<UserRole user_id={self.user_id} role_id={self.role_id}>"


class AccessLog(db.Model):
    __tablename__ = "access_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    path = db.Column(db.String(512), nullable=False)
    method = db.Column(db.String(10), nullable=False)
    ip = db.Column(db.String(64), nullable=True)
    timestamp = db.Column(db.DateTime, server_default=func.now(), nullable=False)


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
