from src.app import app

if __name__ == "__main__":
    from waitress import serve
    print("Iniciando servidor WSGI Waitress en el puerto 5000...")
    serve(app, host='127.0.0.1', port=5000)