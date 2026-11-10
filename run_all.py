# run_all.py - Ejecuta todos los microservicios y el BFF principal de Aceros AZA
import subprocess
import sys
import time

# Lista completa de todos tus microservicios y el BFF central
servicios = [
    {"nombre": "ms_autenticacion", "ruta": "ms_autenticacion/main.py"},
    {"nombre": "ms_calidad", "ruta": "ms_calidad/main.py"},
    {"nombre": "ms_captura", "ruta": "ms_captura/main.py"},
    {"nombre": "ms_modulo_historico", "ruta": "ms_modulo_historico/main.py"},
    {"nombre": "ms_produccion", "ruta": "ms_produccion/main.py"},
    {"nombre": "plantilla_html (BFF Principal)", "ruta": "plantilla_html/src/app.py"}
]

procesos = []

def iniciar_sistema():
    print("==================================================")
    print("   INICIANDO SISTEMA INTEGRADO - ACEROS AZA       ")
    print("==================================================")
    try:
        for serv in servicios:
            print(f"[*] Iniciando {serv['nombre']}...")
            # Lanza cada servicio de manera independiente con el ejecutable de Python
            p = subprocess.Popen([sys.executable, serv['ruta']])
            procesos.append(p)
            time.sleep(1) # Pausa breve para escalonar el arranque
        
        print("\n[✔] ¡Todos los microservicios y el BFF están activos!")
        print("[i] Presiona Ctrl + C en esta terminal para detener todo el sistema.\n")
        
        # Mantiene los procesos corriendo en segundo plano de forma coordinada
        for p in procesos:
            p.wait()

    except KeyboardInterrupt:
        print("\n[!] Deteniendo todos los servicios de Aceros AZA...")
        for p in procesos:
            p.terminate()
        print("[✔] Sistema detenido correctamente.")
        sys.exit(0)

if __name__ == '__main__':
    iniciar_sistema()