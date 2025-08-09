from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, Length, EqualTo


class LoginForm(FlaskForm):
    email = StringField("Usuário ou E-mail", validators=[DataRequired()])
    password = PasswordField("Senha", validators=[DataRequired()])
    submit = SubmitField("Entrar")


class RegisterForm(FlaskForm):
    name = StringField("Nome", validators=[DataRequired(), Length(min=2, max=120)])
    email = StringField("E-mail", validators=[DataRequired(), Email()])
    password = PasswordField(
        "Senha",
        validators=[DataRequired(), Length(min=6)],
    )
    confirm = PasswordField(
        "Confirme a Senha",
        validators=[DataRequired(), EqualTo("password", message="Senhas não conferem")],
    )
    submit = SubmitField("Cadastrar")
