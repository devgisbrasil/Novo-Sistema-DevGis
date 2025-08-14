import click
from app import create_app, db
from app.models import User


@click.group()
def cli():
    pass


@cli.command("create-user")
@click.option("--name", required=True, help="Nome do usuário")
@click.option("--email", required=True, help="E-mail do usuário")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True, help="Senha do usuário")
def create_user(name: str, email: str, password: str):
    """Cria um usuário simples (modelo de acesso aberto, sem papéis)."""
    app = create_app()
    with app.app_context():
        if User.query.filter_by(email=email).first():
            click.echo(f"Usuário já existe: {email}")
            return
        user = User(name=name, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Usuário criado: {email} (nome: {name})")


if __name__ == "__main__":
    cli()
