from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from . import db
from .models import GeoJSONFile
import json
from werkzeug.utils import secure_filename

sig_bp = Blueprint("sig", __name__, url_prefix="/sig")


def _validate_geojson(obj):
    # Very light validation: require type and for FeatureCollection features list
    if not isinstance(obj, dict) or "type" not in obj:
        return False
    t = obj.get("type")
    if t == "FeatureCollection":
        return isinstance(obj.get("features"), list)
    # Allow Feature or Geometry too
    return t in {"Feature", "Point", "LineString", "Polygon", "MultiPoint", "MultiLineString", "MultiPolygon"}


@sig_bp.get("/")
@login_required
def index():
    return render_template("sig/index.html")


@sig_bp.route("/files", methods=["GET", "POST"])
@login_required
def files():
    if request.method == "POST":
        # Upload from file input or raw JSON textarea
        uploaded = request.files.get("file")
        raw = request.form.get("raw_json", "").strip()
        name = request.form.get("name", "").strip()
        try:
            if uploaded and uploaded.filename:
                filename = secure_filename(uploaded.filename)
                content = uploaded.read().decode("utf-8")
                data = json.loads(content)
                if not name:
                    name = filename
            elif raw:
                data = json.loads(raw)
                if not name:
                    name = "GeoJSON sem nome"
            else:
                flash("Selecione um arquivo ou cole um GeoJSON.", "warning")
                return redirect(url_for("sig.files"))

            if not _validate_geojson(data):
                flash("GeoJSON inválido.", "danger")
                return redirect(url_for("sig.files"))

            rec = GeoJSONFile(user_id=current_user.id, name=name, data=data)
            db.session.add(rec)
            db.session.commit()
            flash("GeoJSON salvo com sucesso.", "success")
        except json.JSONDecodeError:
            flash("Conteúdo não é um JSON válido.", "danger")
        except Exception:
            db.session.rollback()
            flash("Erro ao salvar GeoJSON.", "danger")
        return redirect(url_for("sig.files"))

    # GET
    files = GeoJSONFile.query.filter_by(user_id=current_user.id).order_by(GeoJSONFile.created_at.desc()).all()
    return render_template("sig/files.html", files=files)


@sig_bp.post("/files/<int:file_id>/delete")
@login_required
def delete_file(file_id: int):
    rec = GeoJSONFile.query.filter_by(id=file_id, user_id=current_user.id).first()
    if not rec:
        flash("Arquivo não encontrado.", "warning")
        return redirect(url_for("sig.files"))
    try:
        db.session.delete(rec)
        db.session.commit()
        flash("Arquivo removido.", "info")
    except Exception:
        db.session.rollback()
        flash("Erro ao remover arquivo.", "danger")
    return redirect(url_for("sig.files"))


@sig_bp.get("/api/my-geojsons")
@login_required
def api_my_geojsons():
    files = GeoJSONFile.query.filter_by(user_id=current_user.id).all()
    return jsonify([
        {"id": f.id, "name": f.name, "data": f.data} for f in files
    ])


@sig_bp.post("/api/upload")
@login_required
def api_upload():
    """Upload de GeoJSON via API (map page). Aceita multipart com 'file' ou JSON bruto em 'raw_json'."""
    uploaded = request.files.get("file")
    raw = request.form.get("raw_json", "").strip()
    name = request.form.get("name", "").strip()
    try:
        if uploaded and uploaded.filename:
            filename = secure_filename(uploaded.filename)
            content = uploaded.read().decode("utf-8")
            data = json.loads(content)
            if not name:
                name = filename
        elif raw:
            data = json.loads(raw)
            if not name:
                name = "GeoJSON sem nome"
        else:
            return jsonify({"error": "Arquivo ou JSON não fornecido"}), 400

        if not _validate_geojson(data):
            return jsonify({"error": "GeoJSON inválido"}), 400

        rec = GeoJSONFile(user_id=current_user.id, name=name or "Sem nome", data=data)
        db.session.add(rec)
        db.session.commit()
        return jsonify({"id": rec.id, "name": rec.name, "data": rec.data}), 201
    except json.JSONDecodeError:
        return jsonify({"error": "JSON inválido"}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Falha ao salvar"}), 500


@sig_bp.get("/map")
@login_required
def map_view():
    return render_template("sig/map.html")


@sig_bp.post("/load_examples")
@login_required
def load_examples():
    # Load three example files from examples/ into DB for current user
    import os
    base = os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples")
    created = 0
    for fname in ("exemplo1.geojson", "exemplo2.geojson", "exemplo3.geojson"):
        path = os.path.join(base, fname)
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not _validate_geojson(data):
                continue
            rec = GeoJSONFile(user_id=current_user.id, name=fname, data=data)
            db.session.add(rec)
            created += 1
        except Exception:
            db.session.rollback()
    if created:
        db.session.commit()
        flash(f"{created} arquivo(s) de exemplo carregado(s).", "success")
    else:
        flash("Nenhum exemplo carregado.", "warning")
    return redirect(url_for("sig.files"))
