from .db import db

class RegistroHistorico(db.Model):
    __tablename__ = 'registro_historico'
    
    id = db.Column(db.Integer, primary_key=True)
    lote_id = db.Column(db.Integer, nullable=False)
    resultado_final = db.Column(db.String(50), nullable=False)  # Aprobado / Rechazado / Archivado
    fecha_registro = db.Column(db.String(30), nullable=False)

    def __repr__(self):
        return f"<RegistroHistorico Lote ID: {self.lote_id} - {self.resultado_final}>"