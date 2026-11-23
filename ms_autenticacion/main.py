import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import check_password_hash 
from dotenv import load_dotenv
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from shared_auth.security import authenticate

# Carga las variables de entorno desde el archivo .env local
load_dotenv()

app = Flask(__name__)
# El acceso CORS no es necesario por defecto. Solo permitir orígenes confiables.
allowed_origins = [s.strip() for s in os.getenv('AUTH_ALLOWED_ORIGINS', '').split(',') if s.strip()]
if allowed_origins:
    CORS(app, resources={r'/login': {'origins': allowed_origins}})

# Conexión a la base de datos obtenida de forma segura desde el entorno
database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("Error crítico: La variable de entorno DATABASE_URL no está configurada.")

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Modelo para la tabla roles
class Rol(db.Model):
    __tablename__ = 'roles'
    rol_id = db.Column(db.Integer, primary_key=True)
    nombre_rol = db.Column(db.String(50), nullable=False)
    desc_rol = db.Column(db.String(255))

# Modelo para la tabla ficha_personal
class FichaPersonal(db.Model):
    __tablename__ = 'ficha_personal'
    personal_id = db.Column(db.Integer, primary_key=True)
    rol_id = db.Column(db.Integer, db.ForeignKey('roles.rol_id'), nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    apellidos = db.Column(db.String(100), nullable=False)
    rut = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    contrasena_hash = db.Column(db.String(255), nullable=False)
    
    # Relación con Rol
    rol_rel = db.relationship('Rol', backref=db.backref('personal', lazy=True))

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    email = str(data.get('email') or '').strip()[:254]
    password = str(data.get('password') or '')
    conn = None
    try:
        conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
        status, usuario = authenticate(conn, email, password)
        conn.commit()
        if status == 'locked':
            return jsonify({'status': 'error', 'mensaje': 'Acceso temporalmente bloqueado. Intente en 15 minutos.'}), 429
        if status != 'ok':
            return jsonify({'status': 'error', 'mensaje': 'Credenciales inválidas o usuario inactivo.'}), 401
        return jsonify({
            'status': 'success', 'mensaje': 'Autenticación exitosa',
            'nombre': usuario['nombre'], 'email': usuario['email'], 'rol': usuario['rol']
        }), 200
    except Exception:
        if conn:
            conn.rollback()
        app.logger.exception('Error de autenticación del servicio')
        return jsonify({'status': 'error', 'mensaje': 'No se pudo procesar el acceso.'}), 503
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    # Nota: En producción real, asegúrate de cambiar debug=False o controlarlo mediante entorno
    debug_mode = os.getenv("FLASK_DEBUG", "False").lower() == "true"
    app.run(host='0.0.0.0', port=5005, debug=debug_mode)