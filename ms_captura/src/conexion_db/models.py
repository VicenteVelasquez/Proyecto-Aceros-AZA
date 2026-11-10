from .db import db

class AlmacenamientoCaptura(db.Model):
    __tablename__ = 'almacenamiento_captura'
    
    id = db.Column(db.Integer, primary_key=True)
    dispositivo_origen = db.Column(db.String(50), nullable=False)
    datos_json = db.Column(db.Text, nullable=False)  # Simula el almacenamiento de JSON o datos crudos

    def __repr__(self):
        return f"<AlmacenamientoCaptura ID: {self.id} - {self.dispositivo_origen}>"

class LecturaAlambre(db.Model):
    __tablename__ = 'lectura_alambre'
    
    id = db.Column(db.Integer, primary_key=True)
    lote_id = db.Column(db.Integer, nullable=False)
    valor_medido = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.String(30), nullable=False)

    def __repr__(self):
        return f"<LecturaAlambre Valor: {self.valor_medido}>"