from datetime import datetime
from .db import db

class RegistroHistorico(db.Model):
    __tablename__ = 'registro_historico'
    
    id = db.Column(db.Integer, primary_key=True)
    lote_id = db.Column(db.Integer, nullable=False, index=True)
    receta_id = db.Column(db.Integer, nullable=True, index=True)
    operador_id = db.Column(db.Integer, nullable=True, index=True)
    codigo_batch = db.Column(db.String(50), nullable=True)
    angulo_medio = db.Column(db.Float, nullable=False)
    limite_min = db.Column(db.Float, nullable=True)
    limite_max = db.Column(db.Float, nullable=True)
    resultado_final = db.Column(db.String(50), nullable=False, index=True)  # Aprobado / Rechazado / Sin receta
    observacion = db.Column(db.Text, nullable=True)
    foto_url = db.Column(db.String(255), nullable=True)
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Índice compuesto para acelerar consultas históricas por estado y fecha en el panel del Supervisor
    __table_args__ = (
        db.Index('idx_historico_estado_fecha', 'resultado_final', 'fecha_registro'),
    )

    def __repr__(self):
        return f"<RegistroHistorico ID:{self.id} Lote:{self.lote_id} Estado:{self.resultado_final}>"