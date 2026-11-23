"""Bloqueo persistente y transaccional de acceso por usuario en PostgreSQL.

Aplicar antes sql/001_login_lockout.sql. No almacena contraseñas en registros.
"""
from datetime import datetime, timezone, timedelta
from werkzeug.security import check_password_hash

MAX_FAILURES = 3
LOCK_MINUTES = 15


def authenticate(conn, email, password):
    """Devuelve (estado, usuario), estado: ok, invalid, locked, invalid_role.

    Usa SELECT FOR UPDATE en ficha_personal para serializar intentos concurrentes.
    El llamador debe confirmar la transacción mediante commit() o rollback().
    """
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT f.id, f.nombre, f.email, f.contrasena_hash,
                   r.nombre_rol AS rol,
                   f.intentos_fallidos, f.bloqueado_hasta
              FROM ficha_personal f
              JOIN roles r ON f.rol_id = r.id
             WHERE LOWER(TRIM(f.email)) = LOWER(TRIM(%s)) AND f.estado = 'Activo'
             FOR UPDATE OF f;
        """, (email,))
        user = cur.fetchone()
        if not user:
            return 'invalid', None
        now = datetime.now(timezone.utc)
        blocked_until = user['bloqueado_hasta']
        if blocked_until and blocked_until > now:
            return 'locked', None
        # Bloqueo expirado: comienza una cuenta nueva, sin esperar a que alguien lo desbloquee.
        failures = 0 if blocked_until else (user['intentos_fallidos'] or 0)
        if check_password_hash(user['contrasena_hash'], password):
            cur.execute("""
                UPDATE ficha_personal SET intentos_fallidos = 0,
                    bloqueado_hasta = NULL, ultimo_intento_fallido = NULL
                 WHERE id = %s;
            """, (user['id'],))
            return 'ok', user
        failures += 1
        if failures >= MAX_FAILURES:
            cur.execute("""
                UPDATE ficha_personal SET intentos_fallidos = %s,
                    ultimo_intento_fallido = %s, bloqueado_hasta = %s
                 WHERE id = %s;
            """, (failures, now, now + timedelta(minutes=LOCK_MINUTES), user['id']))
            return 'locked', None
        cur.execute("""
            UPDATE ficha_personal SET intentos_fallidos = %s,
                ultimo_intento_fallido = %s, bloqueado_hasta = NULL
             WHERE id = %s;
        """, (failures, now, user['id']))
        return 'invalid', None
    finally:
        cur.close()


def unlock_account(conn, actor_id, actor_role, target_id):
    """Retira bloqueo, con autorización en servidor y bitácora persistente.

    Administrador: cualquier usuario activo. Supervisor: solo rol Operador.
    Retorna 'ok', 'not_found', 'not_locked' o 'forbidden'.
    """
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT f.id, f.bloqueado_hasta, r.nombre_rol AS rol
              FROM ficha_personal f
              JOIN roles r ON r.id = f.rol_id
             WHERE f.id = %s AND f.estado = 'Activo'
             FOR UPDATE OF f;
        """, (target_id,))
        user = cur.fetchone()
        if not user:
            return 'not_found'
        role = str(actor_role or '').strip().casefold()
        target_role = str(user['rol'] or '').strip().casefold()
        if ('admin' not in role and 'supervis' not in role):
            return 'forbidden'
        if 'admin' not in role and target_role not in {'operador', 'operadora', 'operario', 'operator'}:
            return 'forbidden'
        if not user['bloqueado_hasta'] or user['bloqueado_hasta'] <= datetime.now(timezone.utc):
            return 'not_locked'
        cur.execute("""
            UPDATE ficha_personal SET intentos_fallidos = 0,
                bloqueado_hasta = NULL, ultimo_intento_fallido = NULL
             WHERE id = %s;
        """, (target_id,))
        cur.execute("""
            INSERT INTO auditoria_desbloqueos (actor_id, usuario_id, rol_actor)
            VALUES (%s, %s, %s);
        """, (actor_id, target_id, str(actor_role)))
        return 'ok'
    finally:
        cur.close()
