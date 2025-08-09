import click
from app import create_app, db
from app.models import User, Role, UserRole


@click.group()
def cli():
    pass


@cli.command("reset-and-create-admin")
@click.option("--name", "name", default="admin", show_default=True, help="Nome do usuário admin")
@click.option("--email", "email", default="admin@admin.local", show_default=True, help="E-mail do usuário admin")
@click.option("--password", "password", default="admin123", show_default=True, help="Senha do usuário admin")
def reset_and_create_admin(name: str, email: str, password: str):
    """Apaga todos os usuários e cria um superusuário admin."""
    app = create_app()
    with app.app_context():
        # Limpa relacionamentos primeiro
        UserRole.query.delete()
        User.query.delete()
        db.session.commit()

        # Garante o papel admin
        admin_role = Role.query.filter_by(name="admin").first()
        if not admin_role:
            admin_role = Role(name="admin")
            db.session.add(admin_role)
            db.session.commit()

        # Cria usuário admin
        user = User(name=name, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        # Atribui papel admin
        user.roles.append(admin_role)
        db.session.commit()

        click.echo(f"Superusuário criado: {email} (nome: {name})")


if __name__ == "__main__":
    cli()
