from flask import Flask, redirect, url_for, request, render_template, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_bcrypt import Bcrypt
from wtforms import SelectMultipleField
from flask_admin import Admin, expose
from flask_admin.contrib.sqla import ModelView
from flask_admin import AdminIndexView, BaseView
from flask_admin.model import typefmt
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
    class AdminDashboardView(BaseView):
        @expose('/')
        def index(self):
            if not current_user.is_authenticated or not current_user.has_role('admin'):
                return redirect(url_for('auth.login', next=request.url))
            
            from .models import User, Role, AccessLog
            
            # Basic statistics
            stats = {
                'total_users': User.query.count(),
                'total_roles': Role.query.count(),
                'active_users': User.query.filter_by(active=True).count(),
                'today_activities': AccessLog.query.filter(
                    AccessLog.timestamp >= datetime.utcnow().date()
                ).count()
            }
            
            # Get activity data for the last 7 days
            seven_days_ago = datetime.utcnow() - timedelta(days=7)
            activity_data = db.session.query(
                func.date(AccessLog.timestamp).label('date'),
                func.count(AccessLog.id).label('count')
            ).filter(
                AccessLog.timestamp >= seven_days_ago
            ).group_by(
                func.date(AccessLog.timestamp)
            ).order_by(
                func.date(AccessLog.timestamp)
            ).all()
            
            # Format data for chart
            activity_dates = [(datetime.utcnow() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(6, -1, -1)]
            activity_counts = [0] * 7
            
            for data in activity_data:
                if data.date in activity_dates:
                    idx = activity_dates.index(data.date)
                    activity_counts[idx] = data.count
            
            # Get recent activities
            recent_activities = AccessLog.query.order_by(
                AccessLog.timestamp.desc()
            ).limit(10).all()
            
            return self.render('admin/dashboard.html',
                             stats=stats,
                             activity_dates=activity_dates,
                             activity_counts=activity_counts,
                             recent_activities=recent_activities)
    
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

    class RoleModelView(SecureModelView):
        # Configurações da visualização
        can_create = True
        can_edit = True
        can_delete = True
        column_list = ['name', 'description', 'users_count', 'permissions_count', 'created_at', 'updated_at']
        column_searchable_list = ['name', 'description']
        column_filters = ['created_at', 'updated_at']
        form_columns = ['name', 'description', 'users']
        
        # Templates personalizados
        create_template = 'admin/role/create.html'
        edit_template = 'admin/role/create.html'  # Usa o mesmo template para edição
        
        # Formatadores de coluna
        column_formatters = {
            'permissions_count': lambda v, c, m, p: len(m.get_permissions()),
            'users_count': lambda v, c, m, p: len(m.users)
        }
        
        # Configurações dos widgets do formulário
        form_widget_args = {
            'description': {
                'rows': 3
            },
            'users': {
                'class': 'form-control select2',
                'data-placeholder': 'Selecione os usuários...',
                'style': 'width: 100%'
            }
        }
        column_labels = {
            'name': 'Nome do Grupo',
            'description': 'Descrição',
            'created_at': 'Criado em',
            'updated_at': 'Atualizado em',
            'users_count': 'Total de Usuários',
            'permissions_count': 'Permissões',
            'permissions': 'Páginas com Acesso'
        }
        column_descriptions = {
            'name': 'Nome único para identificar o grupo',
            'description': 'Descrição detalhada do propósito do grupo',
            'users': 'Usuários que pertencem a este grupo',
            'permissions': 'Selecione as páginas que este grupo terá acesso'
        }
        
        # Add form_ajax_refs for better user selection
        form_ajax_refs = {
            'users': {
                'fields': ['name', 'email'],
                'page_size': 10,
                'placeholder': 'Pesquisar usuário...',
            }
        }
        
        # Sobrescreve o método create_form para adicionar o campo de permissões
        def create_form(self, obj=None):
            from app.models import Permission
            from wtforms import SelectMultipleField
            
            # Obtém o formulário base
            form = super().create_form(obj)
            
            # Adiciona o campo de permissões
            form.permissions = SelectMultipleField(
                'Páginas com Acesso',
                coerce=int,
                choices=[],  # As opções serão definidas no template
                render_kw={
                    'class': 'form-control select2',
                    'multiple': 'multiple',
                    'data-placeholder': 'Selecione as permissões...',
                    'style': 'width: 100%'
                }
            )
            
            # Define os valores iniciais se estiver editando
            if obj and hasattr(obj, 'role_permissions'):
                form.permissions.data = [p.permission_id for p in obj.role_permissions]
                
            return form
            
        # Sobrescreve o método edit_form para usar a mesma lógica do create_form
        def edit_form(self, obj):
            return self.create_form(obj)
            
        # Sobrescreve o método create_view para passar as permissões para o template
        @expose('/new/', methods=('GET', 'POST'))
        def create_view(self):
            from app.models import Permission
            
            # Chama a implementação padrão
            response = super().create_view()
            
            # Verifica se é uma resposta de renderização
            if hasattr(response, 'get_data') and response.status_code == 200:
                # Obtém o formulário do contexto
                form = self.get_create_form()
                # Obtém todas as permissões
                permissions = Permission.query.order_by('name').all()
                # Adiciona as permissões ao contexto
                return self.render('admin/role/create.html',
                                 form=form,
                                 permissions=permissions)
            
            return response
            
        # Sobrescreve o método edit_view para passar as permissões para o template
        @expose('/edit/', methods=('GET', 'POST'))
        def edit_view(self):
            from app.models import Permission
            
            # Chama a implementação padrão
            response = super().edit_view()
            
            # Verifica se é uma resposta de renderização
            if hasattr(response, 'get_data') and response.status_code == 200:
                # Obtém o formulário do contexto
                form = self.get_edit_form()
                # Obtém todas as permissões
                permissions = Permission.query.order_by('name').all()
                # Adiciona as permissões ao contexto
                return self.render('admin/role/create.html',
                                 form=form,
                                 permissions=permissions)
            
            return response
            
        def edit_form(self, obj):
            return self.create_form(obj)
            
        def on_model_change(self, form, model, is_created):
            from app.models import Permission, RolePermission
            
            # Atualiza os timestamps
            model.updated_at = datetime.utcnow()
            if is_created:
                model.created_at = datetime.utcnow()
            
            # Chama a implementação padrão
            super().on_model_change(form, model, is_created)
            
            # Salva o modelo para obter o ID se for uma criação
            db.session.add(model)
            db.session.flush()
            
            # Processa as permissões se o campo existir no formulário
            if hasattr(form, 'permissions') and hasattr(form.permissions, 'data'):
                try:
                    # Remove as permissões existentes
                    RolePermission.query.filter_by(role_id=model.id).delete()
                    
                    # Adiciona as novas permissões
                    if form.permissions.data:  # Verifica se há permissões para adicionar
                        for perm_id in form.permissions.data:
                            perm = Permission.query.get(perm_id)
                            if perm:
                                role_perm = RolePermission(role_id=model.id, permission_id=perm_id)
                                db.session.add(role_perm)
                    
                    # Salva as alterações
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    flash(f'Erro ao salvar permissões: {str(e)}', 'error')
                    raise
        
        def get_query(self):
            from app.models import User  # Import User model here to avoid circular imports
            return self.session.query(self.model).options(
                db.joinedload(self.model.users).load_only(User.id, User.name, User.email)
            )
            
        def get_count_query(self):
            # Return a simple count of all roles
            return self.session.query(
                db.func.count('*').label('count')
            ).select_from(self.model)
            
        @expose('/permissions/<int:role_id>', methods=('GET', 'POST'))
        def permissions_view(self, role_id):
            role = self.get_one(role_id)
            if not role:
                flash('Grupo não encontrado', 'error')
                return redirect(url_for('.index_view'))
                
            if request.method == 'POST':
                # Update permissions
                permission_names = request.form.getlist('permissions')
                # Remove all current permissions
                RolePermission.query.filter_by(role_id=role_id).delete()
                # Add new permissions
                for perm_name in permission_names:
                    permission = Permission.query.filter_by(name=perm_name).first()
                    if permission:
                        role_permission = RolePermission(role_id=role_id, permission_id=permission.id)
                        db.session.add(role_permission)
                db.session.commit()
                flash('Permissões atualizadas com sucesso!', 'success')
                return redirect(url_for('.permissions_view', role_id=role_id))
                
            # Get all available permissions
            all_permissions = Permission.query.all()
            role_permissions = {rp.permission.name for rp in role.role_permissions}
            
            return self.render('admin/role_permissions.html',
                             role=role,
                             all_permissions=all_permissions,
                             role_permissions=role_permissions)
    
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
        index_view=AdminHomeView(url='/admin', name='Início'),
        base_template="admin/master.html",
    )
    
    # Add custom dashboard view
    admin.add_view(AdminDashboardView(name='Dashboard', endpoint='admin_dashboard', category='Admin'))
    
    # Add model views with custom configurations
    class UserRoleView(SecureModelView):
        column_list = ['user', 'role', 'assigned_at']
        column_labels = {
            'user': 'Usuário',
            'role': 'Grupo',
            'assigned_at': 'Atribuído em'
        }
        column_descriptions = {
            'user': 'Usuário que será vinculado ao grupo',
            'role': 'Grupo que o usuário fará parte'
        }
        form_columns = ['user', 'role']
        column_searchable_list = ['user.name', 'user.email', 'role.name']
        column_filters = ['role.name']
        
        def get_query(self):
            from app.models import User, Role  # Import models here to avoid circular imports
            return self.session.query(UserRole).join(User).join(Role).options(
                db.joinedload(UserRole.user).load_only(User.id, User.name, User.email),
                db.joinedload(UserRole.role).load_only(Role.id, Role.name)
            )
            
        def get_count_query(self):
            # Return a simple count of all user-role relationships
            return self.session.query(db.func.count('*')).select_from(UserRole)
            
        def on_model_change(self, form, model, is_created):
            model.assigned_at = datetime.utcnow()
            return super().on_model_change(form, model, is_created)
            
        def create_form(self, obj=None):
            form = super().create_form(obj)
            # Order users by name and roles by name
            form.user.query = User.query.order_by(User.name)
            form.role.query = Role.query.order_by(Role.name)
            return form
            
        def edit_form(self, obj):
            form = super().edit_form(obj)
            # Order users by name and roles by name
            form.user.query = User.query.order_by(User.name)
            form.role.query = Role.query.order_by(Role.name)
            return form
    
    # Add model views with custom configurations
    admin.add_view(UserModelView(User, db.session, category="Gerenciamento", endpoint="user", name="Usuários"))
    admin.add_view(RoleModelView(Role, db.session, category="Gerenciamento", endpoint="role", name="Grupos"))
    admin.add_view(UserRoleView(UserRole, db.session, category="Gerenciamento", endpoint="userrole", name="Vínculos"))
    admin.add_view(SecureModelView(AccessLog, db.session, category="Logs", endpoint="accesslog"))
    from .models import GeoJSONFile  # noqa: WPS433
    admin.add_view(SecureModelView(GeoJSONFile, db.session, category="SIG", endpoint="geojsonfile"))

    @app.route("/admin")
    def admin_root():
        return redirect("/admin/")

    return app
