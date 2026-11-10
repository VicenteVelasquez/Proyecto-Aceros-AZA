from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Conexión a la base de datos en PostgreSQL (Supabase)
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres.mtccxutquyokrysolcfr:bicho.7892614@aws-1-us-west-2.pooler.supabase.com:6543/postgres'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Modelo para la tabla de lotes de producción
class LoteProduccion(db.Model):
    __tablename__ = 'lotes_produccion'
    id = db.Column(db.Integer, primary_key=True)
    codigo_lote = db.Column(db.String(50), unique=True, nullable=False)
    estado = db.Column(db.String(50), default='Activo')

@app.route('/lotes', methods=['GET'])
def obtener_lotes():
    try:
        lotes = LoteProduccion.query.all()
        resultado = [{
            "id": l.id,
            "codigo_lote": l.codigo_lote,
            "estado": l.estado
        } for l in lotes]
        return jsonify({"status": "success", "lotes": resultado}), 200
    except Exception as e:
        return jsonify({"status": "error", "mensaje": str(e)}), 500

if __name__ == '__main__':
    # Cambiado al puerto 5001 para evitar colisión con ms_modulo_historico (5004)
    app.run(host='0.0.0.0', port=5001, debug=True)