# Sistema de Trazabilidad y Análisis de Producción - Aceros AZA

Plataforma de software desarrollada para la centralización, trazabilidad y análisis posterior de datos productivos en el proceso de fabricación de alambre de **Aceros AZA**. El sistema opera bajo una arquitectura desacoplada de microservicios orientados a servicios y conectados a una base de datos centralizada en PostgreSQL (Supabase).

---

## Arquitectura del Sistema

El proyecto se encuentra estructurado mediante microservicios independientes y un Backend-for-Frontend (BFF) encargado de la interfaz de usuario corporativa:

* **`plantilla_html/`**: Contiene el BFF, las vistas web basadas en plantillas Jinja2 y Bootstrap, el servidor WSGI y la gestión de rutas principales.
* **`ms_autenticacion/`**: Servicio encargado de la gestión de usuarios, roles (RBAC) y validación segura de credenciales mediante algoritmos de hash (`check_password_hash`).
* **`ms_calidad/`**: Administración y control del catálogo de recetas de alambre, ángulos nominales y tolerancias operativas.
* **`ms_produccion/`**: Registro y consulta de lotes de fabricación y estados operativos de la línea industrial.
* **`ms_captura/`**: Módulo de recopilación de mediciones angulares y gestión de alertas del sistema.
* **`ms_modulo_historico/`**: Auditoría y consulta de registros históricos consolidados para el análisis de desviaciones.

---

## Seguridad y Buenas Prácticas

Siguiendo los estándares internacionales de desarrollo seguro y mitigación de riesgos:
* **Variables de Entorno:** Se eliminaron las credenciales hardcodeadas del código fuente. La conexión a la base de datos central se gestiona de forma aislada mediante la directiva `DATABASE_URL`.
* **Control de Secretos:** El archivo de configuración real (`.env`) se encuentra excluido del control de versiones mediante `.gitignore`, asegurando la protección de credenciales sensibles. Se provee una plantilla de ejemplo (`.env.example`) para su correcta inicialización en nuevos entornos.

---

## Requisitos Previos e Instalación

### 1. Clonar el repositorio y configurar el entorno virtual
Abre una terminal en la raíz del proyecto y ejecuta los siguientes comandos para aislar las dependencias:
```bash
python -m venv venv
# Activación en Windows:
venv\Scripts\activate
# Activación en Linux/macOS:
source venv/bin/activate

---

### 2. Instalar dependencias los paquetes necesarios para el funcionamiento del ecosistema Flask
pip install flask flask-sqlalchemy flask-cors python-dotenv waitress

Configuración de Variables de Entorno
Crea un archivo denominado .env dentro de la carpeta plantilla_html (tomando como referencia el archivo .env.example) y configura la cadena de conexión:
DATABASE_URL=postgresql://usuario:contrasena@host:puerto/nombre_base_datos
FLASK_DEBUG=True
Para iniciar la ejecución local del BFF:
cd plantilla_html
python wsgi.py