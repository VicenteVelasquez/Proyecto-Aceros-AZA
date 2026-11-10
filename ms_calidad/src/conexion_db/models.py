from .db import db

class InspeccionCalidad(db.Model):
    __tablename__ = 'inspeccion_calidad'
    
    id = db.Column(db.Integer, primary_key=True)
    lote_id = db.Column(db.Integer, nullable=False)  # Referencia lógica al lote de producción
    diametro_medido = db.Column(db.Float, nullable=False)
    estado_calificacion = db.Column(db.String(30), nullable=False)  # Aprobado / Rechazado
    observaciones = db.Column(db.String(250), nullable=True)

    def __repr__(self):
        return f"<InspeccionCalidad Lote ID: {self.lote_id} - {self.estado_calificacion}>"