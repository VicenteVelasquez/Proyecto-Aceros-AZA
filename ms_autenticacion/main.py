import os
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import check_password_hash 
from dotenv import load_dotenv

# Carga las variables de entorno desde el archivo .env local
load_dotenv()

app = Flask(__name__)
CORS(app)  # Habilita el intercambio de recursos entre puertos

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
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "mensaje": "No se recibieron datos JSON"}), 400
        
    email = data.get('email')
    password = data.get('password')

    # Buscamos al usuario por correo electrónico
    usuario = FichaPersonal.query.filter_by(email=email).first()

    # Validamos usando check_password_hash en lugar de comparación directa
    if usuario and check_password_hash(usuario.contrasena_hash, password):
        # Obtenemos el nombre del rol asociado
        nombre_rol = usuario.rol_rel.nombre_rol if usuario.rol_rel else "Sin Rol"
        
        return jsonify({
            "status": "success",
            "mensaje": "Autenticación exitosa",
            "nombre": f"{usuario.nombre} {usuario.apellidos}",
            "email": usuario.email,
            "rol": nombre_rol
        }), 200
    else:
        return jsonify({
            "status": "error",
            "mensaje": "Correo o contraseña inválidos"
        }), 401

if __name__ == '__main__':
    # Nota: En producción real, asegúrate de cambiar debug=False o controlarlo mediante entorno
    debug_mode = os.getenv("FLASK_DEBUG", "True").lower() == "true"
    app.run(host='0.0.0.0', port=5005, debug=debug_mode)