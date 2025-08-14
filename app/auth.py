from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from . import db
from .models import User
from .forms import LoginForm, RegisterForm

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/login", methods=["GET", "POST"]) 
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.welcome"))
    form = LoginForm()
    if form.validate_on_submit():
        identifier = form.email.data.strip().lower()
        # tenta por email, senão por nome de usuário
        user = User.query.filter_by(email=identifier).first()
        if not user:
            user = User.query.filter(db.func.lower(User.name) == identifier).first()
        if user and user.check_password(form.password.data) and user.active:
            login_user(user, remember=True)
            flash("Login realizado com sucesso.", "success")
            next_page = request.args.get("next")
            return redirect(next_page or url_for("main.welcome"))
        flash("Credenciais inválidas ou usuário inativo.", "danger")
    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Sessão encerrada.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.welcome"))
    form = RegisterForm()
    if form.validate_on_submit():
        if User.query.filter_by(email=form.email.data.lower()).first():
            flash("E-mail já cadastrado.", "warning")
            return render_template("auth/register.html", form=form)
        user = User(name=form.name.data.strip(), email=form.email.data.lower())
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash("Cadastro realizado. Faça o login.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/register.html", form=form)
