from flask import Blueprint, render_template
from flask_login import current_user

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def welcome():
    return render_template("welcome.html", user=current_user)
