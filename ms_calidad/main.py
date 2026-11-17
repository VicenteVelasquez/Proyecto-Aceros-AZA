import os
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from dotenv import load_dotenv

# Carga las variables de entorno desde el archivo .env local
load_dotenv()

app = Flask(__name__)
CORS(app)  # Habilita el intercambio de recursos entre microservicios y el BFF

# Conexión a la base de datos obtenida de forma segura desde el entorno
database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("Error crítico: La variable de entorno DATABASE_URL no está configurada.")

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Modelo para la tabla receta_alambre
class RecetaAlambre(db.Model):
    __tablename__ = 'receta_alambre'
    id = db.Column(db.Integer, primary_key=True)
    codigo_receta = db.Column(db.String(50), unique=True, nullable=False)
    angulo_nominal = db.Column(db.Float, nullable=False)
    tolerancia_min = db.Column(db.Float, nullable=False)
    tolerancia_max = db.Column(db.Float, nullable=False)

# ==========================================
# ENDPOINTS API REST PARA GESTIÓN DE RECETAS
# ==========================================

# 1. Obtener todas las recetas (o filtrar por código si se pasa por query params)
@app.route('/recetas', methods=['GET'])
def obtener_recetas():
    query = request.args.get('q', '').strip()
    try:
        if query:
            recetas = RecetaAlambre.query.filter(RecetaAlambre.codigo_receta.ilike(f"%{query}%")).order_by(RecetaAlambre.id.asc()).all()
        else:
            recetas = RecetaAlambre.query.order_by(RecetaAlambre.id.asc()).all()
            
        resultado = [{
            "id": r.id,
            "codigo_receta": r.codigo_receta,
            "angulo_nominal": r.angulo_nominal,
            "tolerancia_min": r.tolerancia_min,
            "tolerancia_max": r.tolerancia_max
        } for r in recetas]
        
        return jsonify({"status": "success", "recetas": resultado}), 200
    except Exception as e:
        return jsonify({"status": "error", "mensaje": str(e)}), 500

# 2. Crear una nueva receta (Acción de Administrador)
@app.route('/recetas', methods=['POST'])
def crear_receta():
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "mensaje": "No se recibieron datos JSON"}), 400
    
    try:
        nueva_receta = RecetaAlambre(
            codigo_receta=data.get('codigo_receta'),
            angulo_nominal=data.get('angulo_nominal'),
            tolerancia_min=data.get('tolerancia_min'),
            tolerancia_max=data.get('tolerancia_max')
        )
        db.session.add(nueva_receta)
        db.session.commit()
        return jsonify({"status": "success", "mensaje": "Receta creada exitosamente", "id": nueva_receta.id}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "mensaje": str(e)}), 400

# 3. Actualizar una receta existente (Acción de Administrador)
@app.route('/recetas/<int:id_receta>', methods=['PUT'])
def actualizar_receta(id_receta):
    data = request.get_json()
    receta = RecetaAlambre.query.get(id_receta)
    if not receta:
        return jsonify({"status": "error", "mensaje": "Receta no encontrada"}), 404
    
    try:
        receta.codigo_receta = data.get('codigo_receta', receta.codigo_receta)
        receta.angulo_nominal = data.get('angulo_nominal', receta.angulo_nominal)
        receta.tolerancia_min = data.get('tolerancia_min', receta.tolerancia_min)
        receta.tolerancia_max = data.get('tolerancia_max', receta.tolerancia_max)
        db.session.commit()
        return jsonify({"status": "success", "mensaje": "Receta actualizada exitosamente"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "mensaje": str(e)}), 400

# 4. Eliminar una receta (Acción de Administrador)
@app.route('/recetas/<int:id_receta>', methods=['DELETE'])
def eliminar_receta(id_receta):
    receta = RecetaAlambre.query.get(id_receta)
    if not receta:
        return jsonify({"status": "error", "mensaje": "Receta no encontrada"}), 404
    
    try:
        db.session.delete(receta)
        db.session.commit()
        return jsonify({"status": "success", "mensaje": "Receta eliminada exitosamente"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "mensaje": str(e)}), 400

if __name__ == '__main__':
    debug_mode = os.getenv("FLASK_DEBUG", "True").lower() == "true"
    # Lo corremos en el puerto 5002 para que no colisione con autenticación (5005) ni el BFF (5000)
    app.run(host='0.0.0.0', port=5002, debug=debug_mode)