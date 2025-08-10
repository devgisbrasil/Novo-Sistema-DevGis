from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, abort, make_response
from flask_login import login_required, current_user
from . import db
from .models import GeoJSONFile
import json
import os
import tempfile
from werkzeug.utils import secure_filename
import secrets
from fiona.io import ZipMemoryFile
import fiona
from fiona.transform import transform_geom
from shapely.geometry import shape, mapping
import geopandas as gpd
from io import BytesIO
import zipfile

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


def _convert_to_geojson(file_content, filename):
    """Convert various formats to GeoJSON."""
    _, ext = os.path.splitext(filename.lower())
    
    if ext == '.geojson' or ext == '.json':
        try:
            data = json.loads(file_content)
            if _validate_geojson(data):
                return data
        except json.JSONDecodeError:
            pass
    
    # For KML and SHP, we'll use fiona/geopandas
    temp_dir = tempfile.mkdtemp()
    temp_input = os.path.join(temp_dir, f'input{ext}')
    
    try:
        # Write the uploaded content to a temporary file
        with open(temp_input, 'wb') as f:
            if isinstance(file_content, str):
                file_content = file_content.encode('utf-8')
            f.write(file_content)
        
        # Read the file with fiona/geopandas
        if ext == '.kml':
            gdf = gpd.read_file(temp_input, driver='KML')
        elif ext in ['.shp', '.zip']:
            gdf = gpd.read_file(temp_input)
        else:
            return None
            
        # Convert to GeoJSON
        if not gdf.empty:
            # Ensure we're using WGS84 (EPSG:4326)
            if gdf.crs and gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs(epsg=4326)
            return json.loads(gdf.to_json())
            
    except Exception as e:
        print(f"Error converting file: {e}")
        return None
    finally:
        # Clean up temporary files
        try:
            import shutil
            shutil.rmtree(temp_dir)
        except:
            pass
    
    return None


def _create_export_file(geojson_data, export_format):
    """Convert GeoJSON to the requested export format."""
    if not geojson_data:
        return None, None
        
    temp_dir = tempfile.mkdtemp()
    
    try:
        if export_format == 'geojson':
            output = BytesIO()
            output.write(json.dumps(geojson_data, ensure_ascii=False).encode('utf-8'))
            output.seek(0)
            return output, 'application/geo+json'
            
        # Convert to GeoDataFrame for other formats
        gdf = gpd.GeoDataFrame.from_features(geojson_data.get('features', []))
        
        if export_format == 'kml':
            # Create a temporary file for KML
            kml_path = os.path.join(temp_dir, 'export.kml')
            
            # Ensure we have a valid geometry column
            if gdf.geometry.isnull().any():
                gdf = gdf[gdf.geometry.notnull()]
                
            # Convert to WGS84 (EPSG:4326) which is required for KML
            try:
                if not gdf.crs:
                    gdf.crs = 'EPSG:4326'
                gdf = gdf.to_crs('EPSG:4326')
                
                # Save to KML using fiona to avoid issues with GeoPandas KML driver
                schema = {
                    'geometry': gdf.geometry.type.iloc[0] if not gdf.empty else 'Point',
                    'properties': {}
                }
                
                # Save to temporary file
                with fiona.open(
                    kml_path, 'w', 
                    driver='KML', 
                    schema=schema,
                    crs='EPSG:4326'
                ) as dst:
                    for _, row in gdf.iterrows():
                        feature = {
                            'geometry': mapping(row.geometry),
                            'properties': {}
                        }
                        dst.write(feature)
                
                # Read the KML file back into memory
                with open(kml_path, 'rb') as f:
                    output = BytesIO(f.read())
                
                output.seek(0)
                return output, 'application/vnd.google-earth.kml+xml'
                
            except Exception as e:
                print(f"Error creating KML: {e}")
                return None, None
            
        elif export_format == 'shp':
            # Create a zip file with all the shapefile components
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Save to a temp directory first
                temp_shp = os.path.join(temp_dir, 'export.shp')
                
                # Ensure we have a valid geometry column and CRS
                if gdf.geometry.isnull().any():
                    gdf = gdf[gdf.geometry.notnull()]
                if not gdf.crs:
                    gdf.crs = 'EPSG:4326'
                                    gdf.to_file(temp_shp, driver='ESRI Shapefile', encoding='utf-8')
                
                # Add all shapefile components to the zip
                for ext in ['.shp', '.shx', '.dbf', '.prj', '.cpg']:
                    file_path = os.path.join(temp_dir, f'export{ext}')
                    if os.path.exists(file_path):
                        zipf.write(file_path, f'export{ext}')
            
            zip_buffer.seek(0)
            return zip_buffer, 'application/zip'
            
    except Exception as e:
        print(f"Error creating export file: {e}")
        import traceback
        traceback.print_exc()
        return None, None
    finally:
        # Clean up temporary files
        try:
            import shutil
            shutil.rmtree(temp_dir)
        except Exception as e:
            print(f"Error cleaning up temp files: {e}")
    
    return None, None


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
                content = uploaded.read()
                
                # Try to parse as JSON first
                try:
                    data = json.loads(content.decode('utf-8'))
                    if not _validate_geojson(data):
                        # If not valid GeoJSON, try to convert
                        converted = _convert_to_geojson(content, filename)
                        if converted:
                            data = converted
                        else:
                            flash("Arquivo não é um GeoJSON, KML ou SHP válido.", "danger")
                            return redirect(url_for("sig.files"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # If not JSON, try to convert from KML/SHP
                    converted = _convert_to_geojson(content, filename)
                    if converted:
                        data = converted
                    else:
                        flash("Arquivo não é um GeoJSON, KML ou SHP válido.", "danger")
                        return redirect(url_for("sig.files"))
                
                if not name:
                    name = os.path.splitext(filename)[0]  # Remove extension
                    
            elif raw:
                try:
                    data = json.loads(raw)
                    if not _validate_geojson(data):
                        flash("GeoJSON inválido.", "danger")
                        return redirect(url_for("sig.files"))
                except json.JSONDecodeError:
                    flash("Conteúdo não é um JSON válido.", "danger")
                    return redirect(url_for("sig.files"))
                
                if not name:
                    name = "Camada sem nome"
            else:
                flash("Selecione um arquivo ou cole um GeoJSON.", "warning")
                return redirect(url_for("sig.files"))

            rec = GeoJSONFile(user_id=current_user.id, name=name, data=data)
            db.session.add(rec)
            db.session.commit()
            flash("Camada salva com sucesso.", "success")
        except Exception as e:
            db.session.rollback()
            print(f"Error: {str(e)}")
            flash("Erro ao processar o arquivo. Verifique o formato e tente novamente.", "danger")
        return redirect(url_for("sig.files"))

    # GET
    files = GeoJSONFile.query.filter_by(user_id=current_user.id).order_by(GeoJSONFile.created_at.desc()).all()
    return render_template("sig/files.html", files=files)


@sig_bp.get("/files/<int:file_id>/download/<format>")
@login_required
def download_file(file_id: int, format: str):
    """Download a file in the specified format (geojson, kml, shp)."""
    if format not in ['geojson', 'kml', 'shp']:
        abort(400, "Formato inválido. Use 'geojson', 'kml' ou 'shp'.")
    
    rec = GeoJSONFile.query.filter_by(id=file_id, user_id=current_user.id).first_or_404()
    
    output, mime_type = _create_export_file(rec.data, format)
    if not output:
        abort(500, "Erro ao gerar arquivo para download.")
    
    filename = f"{secure_filename(rec.name)}.{format}"
    if format == 'shp':
        filename = f"{secure_filename(rec.name)}.zip"
    
    return send_file(
        output,
        mimetype=mime_type,
        as_attachment=True,
        download_name=filename,
        max_age=0
    )


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


@sig_bp.get("/api/files/<int:file_id>")
@login_required
def api_get_file(file_id: int):
    """Retorna um único GeoJSON do usuário atual pelo id."""
    rec = GeoJSONFile.query.filter_by(id=file_id, user_id=current_user.id).first()
    if not rec:
        return jsonify({"error": "Arquivo não encontrado"}), 404
    return jsonify({"id": rec.id, "name": rec.name, "data": rec.data})


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


@sig_bp.put("/api/files/<int:file_id>")
@login_required
def api_update_file(file_id: int):
    """Atualiza um GeoJSON existente do usuário (somente dono).
    Corpo esperado: JSON com pelo menos a chave 'data' contendo um GeoJSON válido.
    Opcionalmente aceita 'name' para renomear.
    """
    rec = GeoJSONFile.query.filter_by(id=file_id, user_id=current_user.id).first()
    if not rec:
        return jsonify({"error": "Arquivo não encontrado"}), 404

    payload = request.get_json(silent=True) or {}
    data = payload.get("data")
    name = (payload.get("name") or "").strip()

    if data is None:
        return jsonify({"error": "Campo 'data' é obrigatório"}), 400
    if not isinstance(data, dict):
        return jsonify({"error": "'data' deve ser um objeto GeoJSON"}), 400
    if not _validate_geojson(data):
        return jsonify({"error": "GeoJSON inválido"}), 400

    try:
        rec.data = data
        if name:
            rec.name = name
        db.session.commit()
        return jsonify({"id": rec.id, "name": rec.name, "data": rec.data}), 200
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Falha ao atualizar"}), 500


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
