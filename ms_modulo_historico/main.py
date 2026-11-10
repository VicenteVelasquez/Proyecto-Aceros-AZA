from flask import Flask, jsonify
from src.conexion_db.db import db
from src.conexion_db.models import RegistroHistorico

app = Flask(__name__)

# Configuración para evitar problemas con tildes en JSON
app.json.ensure_ascii = False

# Conexión a la base de datos central en PostgreSQL
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres.mtccxutquyokrysolcfr:bicho.7892614@aws-1-us-west-2.pooler.supabase.com:6543/postgres'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "mensaje": "Microservicio de Histórico y Auditoría activo",
        "puerto": 5004,
        "tablas_controladas": ["registro_historico"]
    })

@app.route('/historico', methods=['GET'])
def obtener_historico():
    registros = RegistroHistorico.query.all()
    resultado = [{"id": r.id, "lote_id": r.lote_id, "resultado": r.resultado_final, "fecha": r.fecha_registro} for r in registros]
    return jsonify(resultado)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Crea las tablas de histórico automáticamente en PostgreSQL
    app.run(host='127.0.0.1', port=5004, debug=True)