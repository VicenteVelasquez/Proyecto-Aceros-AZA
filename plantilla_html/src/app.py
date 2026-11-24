from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, Response, make_response
import os
import io
import csv
import hmac
import math
import re
import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.security import check_password_hash, generate_password_hash
import secrets
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
import sys
from zoneinfo import ZoneInfo
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Biblioteca compartida con ms_autenticacion para evitar rutas de acceso sin bloqueo.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from shared_auth.security import authenticate, unlock_account
if __package__:
    from .dashboard_data import get_supervisor_dashboard_data, get_admin_dashboard_data
else:
    from dashboard_data import get_supervisor_dashboard_data, get_admin_dashboard_data
if __package__:
    from .reportes_data import REPORT_TYPES, MAX_EXPORT, MAX_PREVIEW, InvalidReport, get_report, parse_filters
    from .reportes_export import export as export_report
else:
    from reportes_data import REPORT_TYPES, MAX_EXPORT, MAX_PREVIEW, InvalidReport, get_report, parse_filters
    from reportes_export import export as export_report

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')
if not app.secret_key:
    raise RuntimeError('Configure SECRET_KEY en las variables de entorno.')
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.getenv('FLASK_SECURE_COOKIES', '0') == '1',
)
app.config['SIMULATE_USER_STATUS'] = os.getenv('SIMULATE_USER_STATUS') == '1'
CHILE_TIMEZONE = ZoneInfo('America/Santiago')

# Especificaciones oficiales del Alambrón AZA
GRADOS_ACERO_VALIDOS = ['AZA 1006', 'AZA 1008', 'AZA 1013', 'SAE 1008', 'SAE 1010', 'SAE 1020']
DIAMETROS_ESTANDAR = [5.5, 6.0, 6.5, 7.5, 9.5, 11.5]

def turno_actual(now=None):
    current_time = now or datetime.now(CHILE_TIMEZONE)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=CHILE_TIMEZONE)
    else:
        current_time = current_time.astimezone(CHILE_TIMEZONE)
    return 'Turno Mañana' if current_time.hour < 12 else 'Turno Tarde'

# Conexión a la base de datos en PostgreSQL (Supabase)
DB_URI = os.getenv('DATABASE_URL')
if not DB_URI:
    raise RuntimeError('Configure DATABASE_URL en las variables de entorno.')

def get_db_connection():
    conn = psycopg2.connect(DB_URI, cursor_factory=RealDictCursor)
    return conn

def required_text(field, label, max_length, errors):
    value = request.form.get(field, '').strip()
    if not value:
        errors.append(f"{label}: este campo es obligatorio.")
    elif len(value) > max_length:
        errors.append(f"{label}: no puede superar {max_length} caracteres.")
    return value

def nonnegative_number(field, label, errors):
    raw_value = request.form.get(field, '').strip()
    if not raw_value:
        errors.append(f"{label}: este campo es obligatorio.")
        return None
    try:
        value = Decimal(raw_value)
    except InvalidOperation:
        errors.append(f"{label}: debe ser un número válido.")
        return None
    if not value.is_finite():
        errors.append(f"{label}: debe ser un número finito.")
        return None
    if value < 0:
        errors.append(f"{label}: no puede ser negativo.")
        return None
    if value % Decimal('0.1') != 0:
        errors.append(f"{label}: debe usar incrementos de 0,1.")
        return None
    number = float(value)
    if not math.isfinite(number):
        errors.append(f"{label}: está fuera del rango numérico permitido.")
        return None
    return number

def validate_recipe_form():
    errors = []
    code = required_text('codigo_receta', 'Código de receta', 50, errors)
    nominal_field = (
        'angulo_nominal'
        if 'angulo_nominal' in request.form
        else 'calibre_nominal'
    )
    nominal = nonnegative_number(nominal_field, 'Calibre nominal', errors)
    
    if nominal is not None and nominal not in DIAMETROS_ESTANDAR:
        errors.append(f"Calibre nominal: debe ser un valor estándar de AZA ({', '.join(map(str, DIAMETROS_ESTANDAR))} mm).")

    minimum = nonnegative_number('tolerancia_min', 'Tolerancia mínima', errors)
    maximum = nonnegative_number('tolerancia_max', 'Tolerancia máxima', errors)
    if None not in (nominal, minimum, maximum):
        if not minimum <= nominal <= maximum:
            errors.append(
                'Tolerancias: el calibre nominal debe estar entre el mínimo y el máximo.'
            )
    return {'codigo_receta': code, 'angulo_nominal': nominal,
            'tolerancia_min': minimum, 'tolerancia_max': maximum}, errors

def validate_user_form(conn, exclude_id=None, require_password=False):
    errors = []
    values = {
        'nombre': required_text('nombre', 'Nombre', 100, errors),
        'apellidos': required_text('apellidos', 'Apellidos', 100, errors),
        'rut': required_text('rut', 'RUT', 20, errors),
        'email': required_text('email', 'Correo electrónico', 100, errors).casefold(),
    }
    if values['rut'] and not re.fullmatch(r'[0-9.]+-?[0-9kK]', values['rut']):
        errors.append('RUT: use dígitos, puntos opcionales y dígito verificador.')
    if values['email'] and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', values['email']):
        errors.append('Correo electrónico: ingrese una dirección válida.')

    raw_role_id = request.form.get('rol_id', '').strip()
    try:
        values['rol_id'] = int(raw_role_id)
        if values['rol_id'] <= 0:
            raise ValueError
    except ValueError:
        values['rol_id'] = None
        errors.append('Rol: seleccione un rol válido.')

    password = request.form.get('password', '')
    if require_password and not password:
        errors.append('Contraseña: este campo es obligatorio.')
    if password and len(password) < 8:
        errors.append('Contraseña: debe tener al menos 8 caracteres.')
    values['password'] = password

    if values['rol_id'] is not None:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM roles WHERE id = %s;", (values['rol_id'],))
        if cursor.fetchone() is None:
            errors.append('Rol: el rol seleccionado no existe.')
        cursor.close()

    for column, label, value in (
        ('email', 'Correo electrónico', values['email']),
        ('rut', 'RUT', values['rut'])
    ):
        if value:
            cursor = conn.cursor()
            query = f"SELECT id FROM ficha_personal WHERE LOWER(TRIM({column})) = LOWER(TRIM(%s))"
            params = [value]
            if exclude_id is not None:
                query += " AND id <> %s"
                params.append(exclude_id)
            query += " LIMIT 1;"
            cursor.execute(query, tuple(params))
            if cursor.fetchone():
                errors.append(f"{label}: ya está registrado.")
            cursor.close()

    return values, errors

def flash_validation_errors(errors):
    for error in errors:
        flash(error, 'danger')

def role_home_endpoint(role):
    normalized_role = str(role or '').strip().casefold()

    if normalized_role in {'admin', 'administrador', 'administracion', 'administrativo'}:
        return 'admin_dashboard'
    if normalized_role in {'supervisor', 'supervisora', 'supervisores', 'supervision'}:
        return 'supervisor_dashboard'
    if normalized_role in {'operador', 'operator', 'operaria', 'operario'}:
        return 'operador_camara'

    if 'admin' in normalized_role:
        return 'admin_dashboard'
    if 'supervis' in normalized_role:
        return 'supervisor_dashboard'
    if 'operador' in normalized_role or 'operator' in normalized_role:
        return 'operador_camara'

    return None

@app.before_request
def enforce_role_access():
    # Rutas públicas que no requieren validación de rol ni sesión
    rutas_publicas = ['/', '/login', '/logout', '/recuperar-password']
    if request.path in rutas_publicas or request.path.startswith('/reset-password/'):
        return None

    protected_sections = {
        '/admin': 'admin',
        '/supervisor': 'supervisor',
        '/operador': 'operator',
        '/api/operador': 'operator',
        '/api/supervisor': 'supervisor',
        '/api/admin': 'admin',
    }
    required_role = next(
        (role for prefix, role in protected_sections.items()
         if request.path == prefix or request.path.startswith(f'{prefix}/')),
        None
    )
    if required_role is None:
        return None

    if not session.get('user_id'):
        if request.path.startswith('/api/'):
            return jsonify({"status": "error", "mensaje": "Sesión expirada o no autorizada."}), 401
        return redirect(url_for('login_view'))

    # Invalidar sesiones abiertas si la cuenta fue bloqueada, desactivada o cambió de rol.
    # Los permisos se verifican en servidor, no únicamente mediante la cookie firmada.
    verify_conn = None
    try:
        verify_conn = get_db_connection()
        with verify_conn.cursor() as verify_cur:
            verify_cur.execute("""
                SELECT f.estado, f.bloqueado_hasta, COALESCE(r.nombre_rol, '') AS rol
                  FROM ficha_personal f LEFT JOIN roles r ON r.id = f.rol_id
                 WHERE f.id = %s;
            """, (session['user_id'],))
            account = verify_cur.fetchone()
        valid = (
            account is not None
            and account['estado'] == 'Activo'
            and (account['bloqueado_hasta'] is None or account['bloqueado_hasta'] <= datetime.now(timezone.utc))
            and role_home_endpoint(account['rol']) == role_home_endpoint(session.get('user_role'))
        )
        if not valid:
            session.clear()
            if request.path.startswith('/api/'):
                return jsonify({'status': 'error', 'mensaje': 'Acceso suspendido o sesión inválida.'}), 401
            flash('La sesión dejó de estar autorizada. Inicie sesión nuevamente.', 'warning')
            return redirect(url_for('login_view'))
    except Exception:
        app.logger.exception('No se pudo comprobar el estado de la sesión')
        if request.path.startswith('/api/'):
            return jsonify({'status': 'error', 'mensaje': 'No se pudo comprobar la sesión.'}), 503
        return 'No se pudo comprobar la sesión. Intente nuevamente.', 503
    finally:
        if verify_conn:
            verify_conn.close()

    endpoint = role_home_endpoint(session.get('user_role'))
    role_by_endpoint = {
        'admin_dashboard': 'admin',
        'admin_recetas_list': 'admin',
        'supervisor_dashboard': 'supervisor',
        'operador_camara': 'operator',
    }
    current_role = role_by_endpoint.get(endpoint)
    if current_role is None:
        session.clear()
        if request.path.startswith('/api/'):
            return jsonify({"status": "error", "mensaje": "Rol no válido."}), 403
        return redirect(url_for('login_view'))
    if current_role != required_role:
        if request.path.startswith('/api/'):
            return jsonify({"status": "error", "mensaje": "Acceso denegado para su rol."}), 403
        return redirect(url_for(endpoint))
    return None

@app.before_request
def validate_admin_csrf():
    if request.method == 'POST' and (request.path.startswith('/admin/') or request.path.startswith('/supervisor/usuarios-bloqueados/')):
        expected_token = session.get('csrf_token', '')
        submitted_token = request.form.get('csrf_token', '')
        if not expected_token or not hmac.compare_digest(expected_token, submitted_token):
            return 'Formulario vencido o inválido. Recargue la página e inténtelo nuevamente.', 400
    return None

@app.context_processor
def inject_csrf_token():
    def csrf_token():
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_hex(32)
        return session['csrf_token']
    return dict(csrf_token=csrf_token)

# ==========================================
# RUTAS GENERALES Y DE AUTENTICACIÓN
# ==========================================
@app.route('/')
def home():
    return render_template('login.html')

@app.route('/login', methods=['GET', 'POST'])
def login_view():
    error = None
    status_code = 200
    if request.method == 'POST':
        session.clear()
        email = request.form.get('email', '').strip()[:254]
        password = request.form.get('password', '')
        conn = None
        try:
            conn = get_db_connection()
            status, user = authenticate(conn, email, password)
            if status == 'ok':
                endpoint = role_home_endpoint(user['rol'])
                if endpoint is None:
                    conn.rollback()
                    error = 'La cuenta no tiene un rol válido asignado.'
                    status_code = 403
                else:
                    conn.commit()
                    session['user_id'] = user['id']
                    session['user_email'] = user['email']
                    session['user_role'] = user['rol']
                    session['user_nombre'] = user['nombre']
                    return redirect(url_for(endpoint))
            else:
                conn.commit()
                if status == 'locked':
                    error = 'Acceso temporalmente bloqueado. Intente nuevamente en 15 minutos o contacte a un responsable autorizado.'
                    status_code = 429
                else:
                    error = 'Credenciales incorrectas o usuario inactivo.'
                    status_code = 401
        except Exception:
            if conn:
                conn.rollback()
            app.logger.exception('Fallo en autenticación web')
            error = 'No se pudo procesar el acceso. Intente nuevamente más tarde.'
            status_code = 503
        finally:
            if conn:
                conn.close()
    return render_template('login.html', error=error), status_code

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_view'))


# ==========================================
# RECUPERACIÓN Y RESTABLECIMIENTO DE CONTRASEÑA
# ==========================================
@app.route('/recuperar-password', methods=['GET', 'POST'])
def recuperar_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().casefold()
        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT id FROM ficha_personal WHERE LOWER(TRIM(email)) = %s AND estado = 'Activo';", (email,))
            user = cur.fetchone()
            
            if user:
                user_id = user['id'] if isinstance(user, dict) else user[0]
                token = secrets.token_urlsafe(32)
                expiracion = datetime.now() + timedelta(minutes=15)
                
                cur.execute("""
                    UPDATE ficha_personal 
                    SET token_recuperacion = %s, token_expiracion = %s 
                    WHERE id = %s;
                """, (token, expiracion, user_id))
                conn.commit()
                
                # TODO: configurar proveedor de correo transaccional antes de habilitar entrega.
                # Nunca registrar ni mostrar tokens de recuperación en logs.
                flash("El envío de recuperación por correo está pendiente de configuración. Consulte al administrador.", "info")
            else:
                flash("Si el correo está registrado, recibirá las instrucciones en breve.", "info")
                
            cur.close()
            conn.close()
            return redirect(url_for('login_view'))
        except Exception as e:
            if conn: conn.close()
            app.logger.exception('Error solicitando recuperación')
            flash("No se pudo procesar la solicitud.", "danger")
            
    return render_template('auth/recuperar_password.html')


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id FROM ficha_personal 
            WHERE token_recuperacion = %s AND token_expiracion > NOW() AND estado = 'Activo';
        """, (token,))
        user = cur.fetchone()
        
        if not user:
            cur.close()
            conn.close()
            flash("El enlace de recuperación es inválido o ha expirado.", "danger")
            return redirect(url_for('login_view'))
            
        user_id = user['id'] if isinstance(user, dict) else user[0]
        
        if request.method == 'POST':
            nueva_pass = request.form.get('password', '')
            confirm_pass = request.form.get('confirm_password', '')
            
            if len(nueva_pass) < 8:
                flash("La contraseña debe tener al menos 8 caracteres.", "danger")
            elif nueva_pass != confirm_pass:
                flash("Las contraseñas no coinciden.", "danger")
            else:
                nuevo_hash = generate_password_hash(nueva_pass)
                cur.execute("""
                    UPDATE ficha_personal 
                    SET contrasena_hash = %s, token_recuperacion = NULL, token_expiracion = NULL 
                    WHERE id = %s;
                """, (nuevo_hash, user_id))
                conn.commit()
                cur.close()
                conn.close()
                
                flash("Contraseña actualizada exitosamente. Ya puede iniciar sesión.", "success")
                return redirect(url_for('login_view'))
                
        cur.close()
        conn.close()
    except Exception as e:
        if conn: conn.close()
        app.logger.exception('Error restableciendo contraseña')
        flash("No se pudo procesar la solicitud.", "danger")
        return redirect(url_for('login_view'))
        
    return render_template('auth/reset_password.html', token=token)


# ==========================================
# PANEL DE OPERADOR Y OPERACIÓN CONTINUA
# ==========================================
@app.route('/operador')
def operador_view():
    return redirect(url_for('operador_camara'))

@app.route('/operador/camara')
def operador_camara():
    recetas = []
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, codigo_receta, angulo_nominal AS calibre_nominal, tolerancia_min, tolerancia_max 
            FROM receta_alambre 
            ORDER BY id ASC;
        """)
        recetas = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        recetas = []
        
    return render_template(
        'operador/operador_camara.html',
        recetas=recetas,
        turno_actual=turno_actual(),
        estado_tolerancia='Aprobado'
    )

@app.route('/operador/recetas')
def operador_recetas():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, codigo_receta, angulo_nominal AS calibre_nominal, tolerancia_min, tolerancia_max 
            FROM receta_alambre 
            ORDER BY id ASC;
        """)
        recetas = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        recetas = []
    return render_template('operador/operador_recetas.html', recetas=recetas)

@app.route('/operador/alertas')
def operador_alertas():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, lote_id, codigo_batch, fecha_registro AS fecha_hora, 
                   angulo_medio, limite_min, limite_max, resultado_final, 
                   COALESCE(observacion, 'Sin observación') AS observacion,
                   foto_url AS id_alm_cap 
            FROM registro_historico 
            WHERE resultado_final = 'Rechazado' 
            ORDER BY id DESC
            LIMIT 50;
        """)
        alertas = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        alertas = []
    return render_template('operador/operador_alertas.html', alertas=alertas)

@app.route('/operador/resumen')
def operador_resumen():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("SELECT COUNT(*) AS count FROM lote_fabricacion;")
        res1 = cur.fetchone()
        total_lotes = res1['count'] if res1 and 'count' in res1 else 0
        
        cur.execute("SELECT COUNT(*) AS count FROM registro_historico WHERE resultado_final = 'Aprobado';")
        res2 = cur.fetchone()
        total_correctas = res2['count'] if res2 and 'count' in res2 else 0
        
        cur.execute("SELECT COUNT(*) AS count FROM registro_historico WHERE resultado_final = 'Rechazado';")
        res3 = cur.fetchone()
        total_alertas = res3['count'] if res3 and 'count' in res3 else 0
        
        cur.close()
        conn.close()
    except Exception as e:
        total_lotes, total_correctas, total_alertas = 0, 0, 0

    return render_template('operador/operador_resumen.html', 
                           total_lotes=total_lotes, 
                           total_correctas=total_correctas, 
                           total_alertas=total_alertas)

@app.route('/api/recetas/buscar', methods=['GET'])
def api_buscar_recetas():
    query = request.args.get('q', '').strip()
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if query:
            cur.execute("""
                SELECT id, codigo_receta, angulo_nominal, tolerancia_min, tolerancia_max 
                FROM receta_alambre WHERE codigo_receta ILIKE %s ORDER BY id ASC;
            """, (f"%{query}%",))
        else:
            cur.execute("SELECT id, codigo_receta, angulo_nominal, tolerancia_min, tolerancia_max FROM receta_alambre ORDER BY id ASC;")
        recetas = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify({"status": "success", "recetas": recetas}), 200
    except Exception as e:
        return jsonify({"status": "error", "mensaje": str(e)}), 500


# ==========================================
# ENDPOINTS DE CONTROL DE VELOCIDAD Y CÁMARA (1660 FPS)
# ==========================================
@app.route('/api/operador/velocidad', methods=['POST'])
def api_control_velocidad():
    accion = request.form.get('accion', '').strip().lower()
    lote_id = request.form.get('lote_id') or 1
    
    if accion not in ['acelerar', 'ralentizar']:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"status": "error", "mensaje": "Acción de velocidad no válida."}), 400
        flash("Acción de velocidad no válida.", "danger")
        return redirect(url_for('operador_camara'))
    
    try:
        msg = f"Línea ajustada exitosamente ({accion.upper()}). La producción continúa sin detención."
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"status": "success", "mensaje": msg, "accion": accion}), 200
        flash(msg, "info")
        return redirect(url_for('operador_camara'))
    except Exception as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"status": "error", "mensaje": str(e)}), 500
        flash(f"Error al ajustar velocidad: {e}", "danger")
        return redirect(url_for('operador_camara'))


@app.route('/api/operador/registrar_captura', methods=['POST'])
def api_registrar_captura():
    lote_id = request.form.get('lote_id') or 1
    receta_id = request.form.get('receta_id')
    codigo_batch = request.form.get('codigo_batch', 'BATCH-01').strip()
    observacion = request.form.get('observacion', '').strip()
    foto_url = request.form.get('foto_url', 'captura_1660fps.jpg')
    operador_id = session.get('user_id')

    try:
        angulo_medio = float(request.form.get('angulo_medio', 180.0))
        if not (0.0 <= angulo_medio <= 360.0):
            raise ValueError("Ángulo fuera de rango físico (0° - 360°)")
    except (ValueError, TypeError):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"status": "error", "mensaje": "Ángulo inválido."}), 400
        flash("Error: El valor de ángulo enviado no es válido.", "danger")
        return redirect(url_for('operador_camara'))

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        estado_resultado = 'Sin receta'
        tol_min = None
        tol_max = None
        auto_acelerar = False

        if receta_id and str(receta_id).isdigit():
            cur.execute("""
                SELECT tolerancia_min, tolerancia_max, codigo_receta 
                FROM receta_alambre 
                WHERE id = %s;
            """, (int(receta_id),))
            receta = cur.fetchone()

            if receta:
                tol_min = float(receta['tolerancia_min'])
                tol_max = float(receta['tolerancia_max'])

                if tol_min <= angulo_medio <= tol_max:
                    estado_resultado = 'Aprobado'
                    auto_acelerar = True
                else:
                    estado_resultado = 'Rechazado'

        cur.execute("""
            INSERT INTO registro_historico (
                lote_id, receta_id, operador_id, codigo_batch, 
                angulo_medio, limite_min, limite_max, resultado_final, 
                observacion, foto_url, fecha_registro
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            RETURNING id;
        """, (
            int(lote_id),
            int(receta_id) if (receta_id and str(receta_id).isdigit()) else None,
            operador_id,
            codigo_batch,
            angulo_medio,
            tol_min,
            tol_max,
            estado_resultado,
            observacion if observacion else None,
            foto_url
        ))

        nuevo_id = cur.fetchone()
        registro_id = nuevo_id['id']

        conn.commit()
        cur.close()
        conn.close()

        accion_msg = "Ángulo óptimo: auto-acelerando hacia siguiente batch." if auto_acelerar else "Desvío registrado de forma informativa (la línea no se detiene)."
        mensaje_final = f"Batch {codigo_batch} registrado ({angulo_medio}° — {estado_resultado}). {accion_msg}"

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                "status": "success",
                "registro_id": registro_id,
                "estado": estado_resultado,
                "auto_acelerar": auto_acelerar,
                "mensaje": mensaje_final
            }), 200

        flash(mensaje_final, "success" if estado_resultado == "Aprobado" else "warning")
        return redirect(url_for('operador_camara'))

    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"status": "error", "mensaje": str(e)}), 500
        flash(f"Error al registrar batch: {str(e)}", "danger")
        return redirect(url_for('operador_camara'))


@app.route('/api/operador/guardar_observacion', methods=['POST'])
def api_guardar_observacion():
    data = request.get_json(silent=True) or request.form
    observacion = (data.get('observacion') or '').strip()
    registro_id = data.get('registro_id')
    angulo_actual = data.get('angulo_actual', 180.0)

    if not observacion:
        return jsonify({"status": "error", "mensaje": "Debe ingresar una observación antes de guardar."}), 400

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        if registro_id:
            cur.execute("""
                UPDATE registro_historico
                SET observacion = %s
                WHERE id = %s;
            """, (observacion, int(registro_id)))
        else:
            cur.execute("""
                UPDATE registro_historico
                SET observacion = %s
                WHERE id = (SELECT id FROM registro_historico ORDER BY id DESC LIMIT 1);
            """, (observacion,))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            "status": "success",
            "mensaje": f"Observación guardada correctamente (Ángulo: {angulo_actual}°)."
        }), 200

    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({"status": "error", "mensaje": str(e)}), 500


# ==========================================
# PANEL DE SUPERVISOR
# ==========================================
def _dashboard_response(loader, template_name):
    """Obtiene una instantánea real, sin caché ni cifras de relleno."""
    conn = None
    try:
        conn = get_db_connection()
        context = loader(conn)
        response = make_response(render_template(template_name, **context))
        response.headers['Cache-Control'] = 'no-store, private'
        return response
    except Exception:
        app.logger.exception('Error al consultar el dashboard de PostgreSQL')
        if request.path.startswith('/api/'):
            response = make_response('No fue posible actualizar los indicadores.', 503)
        else:
            response = make_response(render_template('errores/dashboard_no_disponible.html'), 503)
        response.headers['Cache-Control'] = 'no-store, private'
        return response
    finally:
        if conn is not None:
            conn.close()


@app.route('/supervisor')
@app.route('/supervisor/dashboard')
def supervisor_dashboard():
    return _dashboard_response(get_supervisor_dashboard_data, 'supervisor/supervisor_dashboard.html')


@app.route('/api/supervisor/dashboard', methods=['GET'])
def api_supervisor_dashboard():
    return _dashboard_response(get_supervisor_dashboard_data, 'supervisor/_dashboard_content.html')


@app.route('/supervisor/alertas', methods=['GET'])
def supervisor_alertas():
    estado_filtro = request.args.get('estado', 'Rechazado').strip()
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        query = """
            SELECT rh.id, 
                   TO_CHAR(rh.fecha_registro, 'YYYY-MM-DD HH24:MI:SS') AS date, 
                   COALESCE(l.codigo_lote, 'LOTE-' || rh.lote_id::text) AS lot, 
                   COALESCE(r.codigo_receta, 'Sin receta') AS recipe, 
                   rh.angulo_medio AS angle, 
                   COALESCE(rh.limite_max, 180.0) AS limit,
                   rh.resultado_final AS estado,
                   COALESCE(rh.observacion, '-') AS observacion
            FROM registro_historico rh
            LEFT JOIN lote_fabricacion l ON rh.lote_id = l.id
            LEFT JOIN receta_alambre r ON rh.receta_id = r.id
            WHERE 1=1
        """
        params = []
        if estado_filtro and estado_filtro != 'Todos':
            query += " AND rh.resultado_final = %s"
            params.append(estado_filtro)
        query += " ORDER BY rh.id DESC LIMIT 25;"

        cur.execute(query, tuple(params))
        raw_alerts = cur.fetchall()
        recent_alerts = []
        for row in raw_alerts:
            recent_alerts.append({
                'date': str(row.get('date', 'N/A')),
                'lot': row.get('lot', 'N/A'),
                'recipe': row.get('recipe', 'Sin receta'),
                'angle': float(row.get('angle') or 0.0),
                'limit': float(row.get('limit') or 180.0),
                'estado': row.get('estado', 'Rechazado'),
                'observacion': row.get('observacion', '-')
            })
            
        cur.execute("""
            SELECT TO_CHAR(fecha_registro, 'Dy') AS day, COUNT(*) AS count 
            FROM registro_historico 
            WHERE resultado_final = 'Rechazado' 
            GROUP BY TO_CHAR(fecha_registro, 'Dy'), DATE(fecha_registro) 
            ORDER BY DATE(fecha_registro) DESC 
            LIMIT 7;
        """)
        raw_days = cur.fetchall()
        alerts_by_day = []
        max_count = max([int(r.get('count', 0)) for r in raw_days], default=10) or 10
        for row in raw_days:
            count = int(row.get('count', 0))
            bar_width = min(int((count / max_count) * 100), 100)
            alerts_by_day.append({'day': row.get('day', 'Día'), 'count': count, 'bar_width': bar_width})
            
        cur.close()
        conn.close()
    except Exception as e:
        recent_alerts = []
        alerts_by_day = []

    if not recent_alerts:
        recent_alerts = [{'date': 'Sin registros', 'lot': 'N/A', 'recipe': 'N/A', 'angle': 0.0, 'limit': 180.0, 'estado': 'N/A', 'observacion': '-'}]
    if not alerts_by_day:
        alerts_by_day = [{'day': 'Hoy', 'count': 0, 'bar_width': 0}]

    dashboard = {'recent_alerts': recent_alerts, 'alerts_by_day': alerts_by_day}
    return render_template('supervisor/supervisor_alertas.html', dashboard=dashboard, estado_filtro=estado_filtro)

@app.route('/supervisor/lotes', methods=['GET'])
def supervisor_lotes():
    lot_query = request.args.get('lote', '').strip()
    selected_date = request.args.get('fecha', '').strip()
    estado_query = request.args.get('estado', '').strip()
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        query = """
            SELECT l.codigo_lote AS code, 
                   TO_CHAR(l.fecha_creacion, 'YYYY-MM-DD HH24:MI') AS date_label, 
                   COALESCE(r.codigo_receta, 'Receta General') AS recipe, 
                   COALESCE(l.estado, 'Activo') AS status 
            FROM lote_fabricacion l
            LEFT JOIN receta_alambre r ON l.receta_id = r.id
            WHERE 1=1
        """
        params = []
        if lot_query:
            query += " AND l.codigo_lote ILIKE %s"
            params.append(f"%{lot_query}%")
        if selected_date:
            query += " AND DATE(l.fecha_creacion) = %s"
            params.append(selected_date)
        if estado_query:
            query += " AND l.estado = %s"
            params.append(estado_query)
            
        query += " ORDER BY l.id DESC LIMIT 50;"
        cur.execute(query, tuple(params))
        raw_lots = cur.fetchall()
        
        lots = []
        for row in raw_lots:
            status = row.get('status', 'Activo')
            style = 'bg-success' if status.lower() == 'activo' else 'bg-secondary'
            lots.append({
                'code': row.get('code', 'LOTE-00'),
                'date_label': row.get('date_label', 'N/A'),
                'recipe': row.get('recipe', 'AZA'),
                'status': status,
                'style': style
            })
        cur.close()
        conn.close()
    except Exception as e:
        lots = []

    return render_template('supervisor/supervisor_lotes.html', lots=lots, lot_query=lot_query, selected_date=selected_date, estado_query=estado_query)

# Los reportes se obtienen del mismo PostgreSQL que alimenta los dashboards.
# El filtrado, la vista previa y los archivos usan una única fuente de datos.
def _report_page(role, template):
    try:
        filters = parse_filters(request.args, role)
    except InvalidReport as exc:
        return render_template(template, report_types=REPORT_TYPES[role],
                               filters={}, report=None, error=str(exc)), 400

    conn = None
    try:
        conn = get_db_connection()
        report = get_report(conn, role, filters, limit=MAX_PREVIEW)
        resp = make_response(render_template(template, report_types=REPORT_TYPES[role],
                                             filters=filters, report=report, error=None))
        resp.headers['Cache-Control'] = 'no-store, private'
        return resp
    except Exception:
        app.logger.exception('No se pudo consultar el reporte en PostgreSQL')
        return render_template(template, report_types=REPORT_TYPES[role], filters=filters,
                               report=None, error='No fue posible consultar los reportes en Supabase.'), 503
    finally:
        if conn is not None:
            conn.close()


def _report_download(role, page_endpoint):
    conn = None
    try:
        formato = (request.args.get('formato') or 'xlsx').lower().strip()
        if formato not in MAX_EXPORT:
            raise InvalidReport('Seleccione un formato de exportación admitido.')
        filters = parse_filters(request.args, role)
        conn = get_db_connection()
        data = get_report(conn, role, filters, limit=MAX_EXPORT[formato])
        content, mime = export_report(data, formato)
        filename = f"aza_{role}_{filters['tipo']}.{formato}"
        resp = make_response(content)
        resp.headers['Content-Type'] = mime
        resp.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        resp.headers['Cache-Control'] = 'no-store, private'
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        return resp
    except InvalidReport as exc:
        return str(exc), 400
    except Exception:
        app.logger.exception('Error al generar un reporte con datos de PostgreSQL')
        return 'No fue posible generar el reporte. Revise la conexión y los registros.', 503
    finally:
        if conn is not None:
            conn.close()


@app.route('/supervisor/reportes', methods=['GET'])
def supervisor_reportes():
    return _report_page('supervisor', 'supervisor/supervisor_reportes.html')


@app.route('/supervisor/reportes/descargar', methods=['GET'])
def supervisor_reportes_descargar():
    return _report_download('supervisor', 'supervisor_reportes')


# ==========================================
# PANEL DE ADMINISTRADOR (CRUDs)
# ==========================================
@app.route('/admin')
@app.route('/admin/dashboard')
def admin_dashboard():
    return _dashboard_response(get_admin_dashboard_data, 'administrador/admin_dashboard.html')


@app.route('/api/admin/dashboard', methods=['GET'])
def api_admin_dashboard():
    return _dashboard_response(get_admin_dashboard_data, 'administrador/_dashboard_content.html')


# --- CRUD Recetas ---
@app.route('/admin/recetas', methods=['GET'])
def admin_recetas_list():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, codigo_receta, angulo_nominal AS calibre_nominal, tolerancia_min, tolerancia_max 
            FROM receta_alambre 
            ORDER BY id ASC;
        """)
        recetas = cur.fetchall()
        cur.close()
        conn.close()
        error = None
    except Exception as e:
        recetas = []
        error = f"Error al cargar las recetas: {e}"
    return render_template('administrador/admin_recetas.html', recetas=recetas, error=error, demo_mode=False)

@app.route('/admin/recetas/crear', methods=['POST'])
def admin_recetas_crear():
    values, errors = validate_recipe_form()
    if errors:
        flash_validation_errors(errors)
        return redirect(url_for('admin_recetas_list'))

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM receta_alambre WHERE LOWER(TRIM(codigo_receta)) = LOWER(TRIM(%s)) LIMIT 1;",
            (values['codigo_receta'],)
        )
        if cur.fetchone():
            flash('Código de receta: ya está registrado.', 'danger')
            return redirect(url_for('admin_recetas_list'))
        cur.execute("""
            INSERT INTO receta_alambre (codigo_receta, angulo_nominal, tolerancia_min, tolerancia_max)
            VALUES (%s, %s, %s, %s);
        """, (values['codigo_receta'], values['angulo_nominal'],
              values['tolerancia_min'], values['tolerancia_max']))
        conn.commit()
        flash('Receta creada correctamente.', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash('No se pudo crear la receta. Revise que el código no esté duplicado.', 'danger')
    finally:
        if cur: cur.close()
        if conn: conn.close()
    return redirect(url_for('admin_recetas_list'))

@app.route('/admin/recetas/editar/<int:id>', methods=['POST'])
def admin_recetas_editar(id):
    values, errors = validate_recipe_form()
    if errors:
        flash_validation_errors(errors)
        return redirect(url_for('admin_recetas_list'))

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM receta_alambre WHERE id = %s;", (id,))
        if cur.fetchone() is None:
            flash('La receta que intenta editar ya no existe.', 'danger')
            return redirect(url_for('admin_recetas_list'))
        cur.execute("""
            UPDATE receta_alambre 
            SET codigo_receta = %s, angulo_nominal = %s, tolerancia_min = %s, tolerancia_max = %s
            WHERE id = %s;
        """, (values['codigo_receta'], values['angulo_nominal'],
              values['tolerancia_min'], values['tolerancia_max'], id))
        conn.commit()
        flash('Receta actualizada correctamente.', 'success')
    except Exception as e:
        if conn: conn.rollback()
        flash('No se pudo actualizar la receta.', 'danger')
    finally:
        if cur: cur.close()
        if conn: conn.close()
    return redirect(url_for('admin_recetas_list'))

@app.route('/admin/recetas/eliminar/<int:id>', methods=['POST'])
def admin_recetas_eliminar(id):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE receta_alambre SET estado = 'Inactivo' WHERE id = %s;", (id,))
        conn.commit()
        flash('Receta desactivada correctamente.', 'success')
    except Exception as e:
        if conn: conn.rollback()
        flash('No se pudo desactivar la receta.', 'danger')
    finally:
        if cur: cur.close()
        if conn: conn.close()
    return redirect(url_for('admin_recetas_list'))

@app.route('/admin/recetas/activar/<int:id>', methods=['POST'])
def admin_recetas_activar(id):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE receta_alambre SET estado = 'Activo' WHERE id = %s;", (id,))
        conn.commit()
        flash('Receta activada correctamente.', 'success')
    except Exception as e:
        if conn: conn.rollback()
        flash('No se pudo activar la receta.', 'danger')
    finally:
        if cur: cur.close()
        if conn: conn.close()
    return redirect(url_for('admin_recetas_list'))

# --- CRUD Usuarios ---
@app.route('/admin/usuarios', methods=['GET'])
def admin_usuarios_list():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT f.id, f.nombre, f.apellidos, f.email, f.rut, 
                   COALESCE(r.nombre_rol, 'Operador') AS rol, 
                   COALESCE(f.estado, 'Activo') AS estado,
                   (f.bloqueado_hasta > NOW()) AS bloqueo_activo,
                   TO_CHAR(f.bloqueado_hasta AT TIME ZONE 'America/Santiago', 'DD/MM/YYYY HH24:MI') AS bloqueo_hasta_local
            FROM ficha_personal f
            LEFT JOIN roles r ON f.rol_id = r.id
            ORDER BY f.id ASC;
        """)
        usuarios = cur.fetchall()
        cur.execute("SELECT id, nombre_rol FROM roles ORDER BY id ASC;")
        roles = cur.fetchall()
        cur.close()
        conn.close()
        error = None
    except Exception as e:
        usuarios, roles = [], []
        error = f"Error al cargar los usuarios: {e}"

    return render_template(
        'administrador/admin_usuarios.html',
        usuarios=usuarios,
        roles=roles,
        error=error,
        demo_mode=False,
        management_enabled=True,
        simulate_user_status=app.config['SIMULATE_USER_STATUS']
    )

@app.route('/admin/usuarios/crear', methods=['POST'])
def admin_usuarios_crear():
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        values, errors = validate_user_form(conn, require_password=True)
        if errors:
            flash_validation_errors(errors)
            return redirect(url_for('admin_usuarios_list'))

        cur = conn.cursor()
        cur.execute("""
            INSERT INTO ficha_personal (nombre, apellidos, rut, email, rol_id, contrasena_hash, estado)
            VALUES (%s, %s, %s, %s, %s, %s, 'Activo');
        """, (values['nombre'], values['apellidos'], values['rut'],
              values['email'], values['rol_id'],
              generate_password_hash(values['password'])))
        conn.commit()
        flash('Usuario creado correctamente.', 'success')
    except Exception as e:
        if conn: conn.rollback()
        flash('No se pudo crear el usuario.', 'danger')
    finally:
        if cur: cur.close()
        if conn: conn.close()
    return redirect(url_for('admin_usuarios_list'))

@app.route('/admin/usuarios/editar/<int:id>', methods=['POST'])
def admin_usuarios_editar(id):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        values, errors = validate_user_form(conn, exclude_id=id)
        if errors:
            flash_validation_errors(errors)
            return redirect(url_for('admin_usuarios_list'))

        cur = conn.cursor()
        if values['password']:
            contrasena_hash = generate_password_hash(values['password'])
            cur.execute("""
                UPDATE ficha_personal 
                SET nombre = %s, apellidos = %s, rut = %s, email = %s, rol_id = %s, contrasena_hash = %s
                WHERE id = %s;
            """, (values['nombre'], values['apellidos'], values['rut'],
                  values['email'], values['rol_id'], contrasena_hash, id))
        else:
            cur.execute("""
                UPDATE ficha_personal 
                SET nombre = %s, apellidos = %s, rut = %s, email = %s, rol_id = %s
                WHERE id = %s;
            """, (values['nombre'], values['apellidos'], values['rut'],
                  values['email'], values['rol_id'], id))
        conn.commit()
        flash('Usuario actualizado correctamente.', 'success')
    except Exception as e:
        if conn: conn.rollback()
        flash('No se pudo actualizar el usuario.', 'danger')
    finally:
        if cur: cur.close()
        if conn: conn.close()
    return redirect(url_for('admin_usuarios_list'))

@app.route('/admin/usuarios/desactivar/<int:id>', methods=['POST'])
def admin_usuarios_desactivar(id):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE ficha_personal SET estado = 'Inactivo' WHERE id = %s;", (id,))
        conn.commit()
        flash('Usuario desactivado correctamente.', 'success')
    except Exception as e:
        if conn: conn.rollback()
        flash('No se pudo desactivar el usuario.', 'danger')
    finally:
        if cur: cur.close()
        if conn: conn.close()
    return redirect(url_for('admin_usuarios_list'))

@app.route('/admin/usuarios/activar/<int:id>', methods=['POST'])
def admin_usuarios_activar(id):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE ficha_personal SET estado = 'Activo' WHERE id = %s;", (id,))
        conn.commit()
        flash('Usuario activado correctamente.', 'success')
    except Exception as e:
        if conn: conn.rollback()
        flash('No se pudo activar el usuario.', 'danger')
    finally:
        if cur: cur.close()
        if conn: conn.close()
    return redirect(url_for('admin_usuarios_list'))

# --- Desbloqueo de seguridad: cambios autorizados y auditados ---
@app.route('/admin/usuarios/desbloquear/<int:id>', methods=['POST'])
def admin_usuarios_desbloquear(id):
    return process_manual_unlock(id, 'admin_usuarios_list')

@app.route('/supervisor/usuarios-bloqueados', methods=['GET'])
def supervisor_usuarios_bloqueados():
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT f.id, f.nombre, f.apellidos, f.email,
                       TO_CHAR(f.bloqueado_hasta AT TIME ZONE 'America/Santiago', 'DD/MM/YYYY HH24:MI') AS bloqueo_hasta_local
                FROM ficha_personal f JOIN roles r ON r.id = f.rol_id
                WHERE LOWER(TRIM(r.nombre_rol)) IN ('operador', 'operadora', 'operario', 'operator')
                  AND f.estado = 'Activo' AND f.bloqueado_hasta > NOW()
                ORDER BY f.bloqueado_hasta ASC;
            """)
            usuarios = cur.fetchall()
        return render_template('supervisor/supervisor_usuarios_bloqueados.html', usuarios=usuarios, error=None)
    except Exception:
        app.logger.exception('No se pudieron consultar bloqueos')
        return render_template('supervisor/supervisor_usuarios_bloqueados.html', usuarios=[], error='No se pudieron consultar los bloqueos.'), 503
    finally:
        if conn:
            conn.close()

@app.route('/supervisor/usuarios-bloqueados/desbloquear/<int:id>', methods=['POST'])
def supervisor_usuarios_desbloquear(id):
    return process_manual_unlock(id, 'supervisor_usuarios_bloqueados')

def process_manual_unlock(target_id, return_endpoint):
    conn = None
    try:
        conn = get_db_connection()
        status = unlock_account(conn, session.get('user_id'), session.get('user_role'), target_id)
        if status == 'forbidden':
            conn.rollback()
            return 'No tiene permisos para desbloquear esta cuenta.', 403
        if status == 'ok':
            conn.commit()
            flash('Bloqueo de inicio de sesión retirado. Acción registrada en auditoría.', 'success')
        else:
            conn.rollback()
            flash('La cuenta no tiene un bloqueo vigente o no existe.', 'warning')
    except Exception:
        if conn:
            conn.rollback()
        app.logger.exception('No se pudo desbloquear cuenta')
        flash('No fue posible desbloquear la cuenta.', 'danger')
    finally:
        if conn:
            conn.close()
    return redirect(url_for(return_endpoint))

# --- CRUD Producción ---
@app.route('/admin/produccion', methods=['GET'])
def admin_produccion_list():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, codigo_lote, estado FROM lote_fabricacion ORDER BY id ASC;")
        lotes = cur.fetchall()
        cur.close()
        conn.close()
        error = None
    except Exception as e:
        lotes = []
        error = f"Error al cargar los lotes de producción: {e}"
    return render_template('administrador/admin_produccion.html', lotes=lotes, error=error, demo_mode=False, management_enabled=True)

@app.route('/admin/produccion/crear', methods=['POST'])
def admin_produccion_crear():
    errors = []
    codigo_lote = required_text('codigo_lote', 'Código de lote', 50, errors)
    if errors:
        flash_validation_errors(errors)
        return redirect(url_for('admin_produccion_list'))

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO lote_fabricacion (codigo_lote, estado) VALUES (%s, 'Activo');", (codigo_lote,))
        conn.commit()
        flash('Lote creado correctamente.', 'success')
    except Exception as e:
        if conn: conn.rollback()
        flash('No se pudo crear el lote.', 'danger')
    finally:
        if cur: cur.close()
        if conn: conn.close()
    return redirect(url_for('admin_produccion_list'))

@app.route('/admin/produccion/editar/<int:id>', methods=['POST'])
def admin_produccion_editar(id):
    errors = []
    codigo_lote = required_text('codigo_lote', 'Código de lote', 50, errors)
    estado = request.form.get('estado', '').strip()
    if errors:
        flash_validation_errors(errors)
        return redirect(url_for('admin_produccion_list'))

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE lote_fabricacion SET codigo_lote = %s, estado = %s WHERE id = %s;", (codigo_lote, estado, id))
        conn.commit()
        flash('Lote actualizado correctamente.', 'success')
    except Exception as e:
        if conn: conn.rollback()
        flash('No se pudo actualizar el lote.', 'danger')
    finally:
        if cur: cur.close()
        if conn: conn.close()
    return redirect(url_for('admin_produccion_list'))

@app.route('/admin/produccion/desactivar/<int:id>', methods=['POST'])
def admin_produccion_desactivar(id):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE lote_fabricacion SET estado = 'Inactivo' WHERE id = %s;", (id,))
        conn.commit()
        flash('Lote desactivado correctamente.', 'success')
    except Exception as e:
        if conn: conn.rollback()
        flash('No se pudo desactivar el lote.', 'danger')
    finally:
        if cur: cur.close()
        if conn: conn.close()
    return redirect(url_for('admin_produccion_list'))

# --- Reportes Administración ---
@app.route('/admin/reportes', methods=['GET'])
def admin_reportes_list():
    return _report_page('admin', 'administrador/admin_reportes.html')


@app.route('/admin/reportes/descargar', methods=['GET'])
def admin_reportes_descargar():
    return _report_download('admin', 'admin_reportes_list')


# ==========================================
# MANEJADORES DE ERRORES HTTP (Apuntando a errores/)
# ==========================================
@app.errorhandler(403)
def error_403(e):
    return render_template('errores/403.html'), 403

@app.errorhandler(404)
def error_404(e):
    return render_template('errores/404.html'), 404

@app.errorhandler(500)
def error_500(e):
    return render_template('errores/500.html'), 500


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=os.getenv('FLASK_DEBUG', 'false').lower() == 'true')