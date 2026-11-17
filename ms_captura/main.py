import os
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from dotenv import load_dotenv

# Carga las variables de entorno desde el archivo .env local
load_dotenv()

app = Flask(__name__)
CORS(app)

# Conexión a la base de datos obtenida de forma segura desde el entorno
database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("Error crítico: La variable de entorno DATABASE_URL no está configurada.")

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Modelo para la tabla de lecturas M2M
class LecturaAlambre(db.Model):
    __tablename__ = 'lectura_alambre'
    id = db.Column(db.Integer, primary_key=True)
    angulo_medido = db.Column(db.Float, nullable=False)
    estado_alerta = db.Column(db.Boolean, default=False)

@app.route('/capturas', methods=['GET'])
def obtener_capturas():
    try:
        lecturas = LecturaAlambre.query.all()
        resultado = [{
            "id": l.id,
            "angulo_medido": l.angulo_medido,
            "estado_alerta": l.estado_alerta
        } for l in lecturas]
        return jsonify({"status": "success", "capturas": resultado}), 200
    except Exception as e:
        return jsonify({"status": "error", "mensaje": str(e)}), 500

if __name__ == '__main__':
    debug_mode = os.getenv("FLASK_DEBUG", "True").lower() == "true"
    app.run(host='0.0.0.0', port=5003, debug=debug_mode)