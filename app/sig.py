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

# Storage for orthomosaics (GeoTIFFs)
ORTHO_DIR = os.getenv(
    "ORTHO_DIR",
    os.path.join(os.path.dirname(__file__), "storage", "orthomosaics"),
)
ALLOWED_ORTHO_EXTS = {".tif", ".tiff", ".geotiff"}

# Ensure directory exists at runtime
os.makedirs(ORTHO_DIR, exist_ok=True)


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
    """
    Upload de GeoJSON via API (map page). 
    Aceita:
    - multipart/form-data com 'file' (arquivo)
    - application/json com 'data' (GeoJSON) e 'name' (opcional)
    - application/x-www-form-urlencoded com 'raw_json' e 'name'
    """
    try:
        # Handle JSON content type
        if request.is_json:
            json_data = request.get_json()
            data = json_data.get('data')
            name = json_data.get('name', 'Meu Desenho').strip()
            if not data:
                return jsonify({"error": "Campo 'data' não encontrado no JSON"}), 400
        else:
            # Handle form data
            uploaded = request.files.get("file")
            raw = request.form.get("raw_json", "").strip()
            name = request.form.get("name", "").strip()
            
            if uploaded and uploaded.filename:
                # Handle file upload
                filename = secure_filename(uploaded.filename)
                content = uploaded.read().decode("utf-8")
                data = json.loads(content)
                if not name:
                    name = os.path.splitext(filename)[0]  # Remove a extensão do arquivo
            elif raw:
                # Handle raw JSON from form
                data = json.loads(raw)
                if not name:
                    name = "Meu Desenho"
            else:
                return jsonify({"error": "Nenhum dado fornecido. Envie um arquivo ou JSON."}), 400
        
        # Validate the GeoJSON data
        if not _validate_geojson(data):
            return jsonify({"error": "GeoJSON inválido. Certifique-se de que é um FeatureCollection, Feature ou Geometry válido."}), 400
        
        # Ensure we have a valid name
        if not name:
            name = "Meu Desenho"
        
        # Ensure the name is unique by appending a number if needed
        base_name = name
        counter = 1
        while GeoJSONFile.query.filter_by(user_id=current_user.id, name=name).first() is not None:
            name = f"{base_name} ({counter})"
            counter += 1
        
        # Create and save the new record
        rec = GeoJSONFile(
            user_id=current_user.id, 
            name=name,
            data=data
        )
        
        db.session.add(rec)
        db.session.commit()
        
        return jsonify({
            "id": rec.id, 
            "name": rec.name,
            "message": "Desenho salvo com sucesso!"
        }), 201
        
    except json.JSONDecodeError as e:
        return jsonify({"error": f"Erro ao decodificar JSON: {str(e)}"}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Erro ao processar a requisição: {str(e)}"}), 500
        return jsonify({"error": "Falha ao salvar"}), 500


@sig_bp.get("/map")
@login_required
def map_view():
    return render_template("sig/map.html")


# ----------------------
# Orthomosaics management
# ----------------------

def _is_allowed_ortho(filename: str):
    ext = os.path.splitext(filename.lower())[1]
    return ext in ALLOWED_ORTHO_EXTS


@sig_bp.get("/orthomosaics")
@login_required
def orthomosaics_index():
    """List available orthomosaics and show upload form."""
    try:
        files = []
        for fname in sorted(os.listdir(ORTHO_DIR)):
            path = os.path.join(ORTHO_DIR, fname)
            if os.path.isfile(path) and _is_allowed_ortho(fname):
                stat = os.stat(path)
                files.append({
                    "name": fname,
                    "size": stat.st_size,
                })
    except Exception as e:
        flash(f"Erro ao listar ortomosaicos: {e}", "danger")
        files = []
    return render_template("sig/orthomosaics.html", files=files)


@sig_bp.post("/orthomosaics/upload")
@login_required
def orthomosaics_upload():
    """Handle upload of GeoTIFF files (.tif/.tiff/.geotiff)."""
    if "file" not in request.files:
        flash("Nenhum arquivo enviado.", "warning")
        return redirect(url_for("sig.orthomosaics_index"))

    f = request.files.get("file")
    if not f or f.filename.strip() == "":
        flash("Arquivo inválido.", "warning")
        return redirect(url_for("sig.orthomosaics_index"))

    filename = secure_filename(f.filename)
    if not _is_allowed_ortho(filename):
        flash("Formato não suportado. Envie .tif, .tiff ou .geotiff.", "danger")
        return redirect(url_for("sig.orthomosaics_index"))

    # Ensure unique filename to avoid overwrite
    base, ext = os.path.splitext(filename)
    candidate = filename
    counter = 1
    while os.path.exists(os.path.join(ORTHO_DIR, candidate)):
        candidate = f"{base}_{counter}{ext}"
        counter += 1

    save_path = os.path.join(ORTHO_DIR, candidate)
    try:
        f.save(save_path)
        flash("Upload realizado com sucesso!", "success")
    except Exception as e:
        flash(f"Erro ao salvar arquivo: {e}", "danger")

    return redirect(url_for("sig.orthomosaics_index"))


@sig_bp.get("/orthomosaics/download/<path:filename>")
@login_required
def orthomosaics_download(filename: str):
    """Secure download of a stored orthomosaic."""
    safe_name = secure_filename(filename)
    path = os.path.join(ORTHO_DIR, safe_name)
    if not os.path.exists(path) or not _is_allowed_ortho(safe_name):
        abort(404)
    try:
        # as_attachment to force proper download with file name
        return send_file(path, as_attachment=True, download_name=safe_name)
    except Exception:
        abort(500)


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
