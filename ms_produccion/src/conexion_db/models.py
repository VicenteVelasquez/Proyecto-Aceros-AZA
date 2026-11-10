from .db import db

class Turno(db.Model):
    __tablename__ = 'turno'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False)  # Ej: Mañana, Tarde, Noche
    descripcion = db.Column(db.String(200), nullable=True)

    def __repr__(self):
        return f"<Turno {self.nombre}>"

class RecetaAlambre(db.Model):
    __tablename__ = 'receta_alambre'
    
    id = db.Column(db.Integer, primary_key=True)
    codigo_receta = db.Column(db.String(50), unique=True, nullable=False)
    calibre_nominal = db.Column(db.Float, nullable=False)
    tolerancia_min = db.Column(db.Float, nullable=False)
    tolerancia_max = db.Column(db.Float, nullable=False)

    def __repr__(self):
        return f"<RecetaAlambre {self.codigo_receta}>"

class LoteFabricacion(db.Model):
    __tablename__ = 'lote_fabricacion'
    
    id = db.Column(db.Integer, primary_key=True)
    codigo_lote = db.Column(db.String(50), unique=True, nullable=False)
    turno_id = db.Column(db.Integer, db.ForeignKey('turno.id'), nullable=False)
    receta_id = db.Column(db.Integer, db.ForeignKey('receta_alambre.id'), nullable=False)
    estado = db.Column(db.String(30), default='En Proceso')

    def __repr__(self):
        return f"<LoteFabricacion {self.codigo_lote}>"