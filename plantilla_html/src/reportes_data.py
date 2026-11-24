"""Reportes de Aceros AZA basados exclusivamente en PostgreSQL.

En particular, una lectura dentro de tolerancia NO aprueba un lote y
un lote registrado NO representa toneladas de acero producido.
"""
from datetime import datetime

REPORT_TYPES = {
    'supervisor': {
        'resumen_general': ('Mediciones históricas', 'lecturas'),
        'produccion_diaria': ('Lotes registrados por día', 'produccion'),
        'tendencia_calidad': ('Tendencia diaria de tolerancias', 'calidad'),
        'alertas_activas': ('Mediciones fuera de tolerancia', 'alertas'),
    },
    'admin': {
        'general': ('Historial general de mediciones', 'lecturas'),
        'produccion': ('Lotes registrados por día', 'produccion'),
        'calidad': ('Tendencia diaria de tolerancias', 'calidad'),
        'lotes': ('Lotes y lecturas relacionadas', 'lotes'),
        'auditoria_accesos': ('Auditoría de bloqueos y desbloqueos', 'auditoria'),
        'cuentas_bloqueadas': ('Cuentas con bloqueo vigente', 'bloqueados'),
    },
}

COLUMNS = {
    'lecturas': [
        ('registro_id', 'ID'), ('fecha', 'Fecha de captura'),
        ('lote', 'Lote'), ('receta', 'Receta'), ('batch', 'Batch'),
        ('angulo', 'Ángulo medido'), ('limite_min', 'Límite mín.'),
        ('limite_max', 'Límite máx.'), ('resultado', 'Resultado de lectura'),
        ('observacion', 'Observación'),
    ],
    'produccion': [
        ('dia', 'Día'), ('lotes', 'Lotes registrados'),
        ('activos', 'Lotes activos'), ('otros', 'Otros estados'),
    ],
    'calidad': [
        ('dia', 'Día'), ('lecturas', 'Lecturas'),
        ('dentro', 'Dentro de tolerancia'), ('fuera', 'Fuera de tolerancia'),
        ('sin_clasificar', 'Sin clasificación'),
        ('porcentaje', '% dentro de tolerancia (clasificadas)'),
    ],
    'auditoria': [
        ('fecha', 'Fecha (Chile)'), ('evento', 'Evento'),
        ('usuario_id', 'ID usuario'), ('usuario', 'Usuario afectado'),
        ('rol_usuario', 'Perfil'), ('actor', 'Desbloqueado por'),
        ('rol_actor', 'Rol responsable'), ('bloqueado_hasta', 'Bloqueo hasta (Chile)'),
        ('intentos_fallidos', 'Intentos al bloquear'),
    ],
    'bloqueados': [
        ('usuario_id', 'ID usuario'), ('usuario', 'Usuario'),
        ('rol_usuario', 'Perfil'), ('intentos_fallidos', 'Intentos fallidos'),
        ('ultimo_intento', 'Último intento (Chile)'),
        ('bloqueado_hasta', 'Bloqueado hasta (Chile)'),
    ],
    'lotes': [
        ('lote_id', 'ID lote'), ('lote', 'Código de lote'),
        ('fecha', 'Fecha de inicio'), ('receta', 'Receta'),
        ('estado', 'Estado del lote'), ('lecturas', 'Lecturas del lote'),
        ('fuera', 'Lecturas fuera de tolerancia'),
    ],
}

MAX_PREVIEW = 30
MAX_EXPORT = {'csv': 5000, 'xlsx': 5000, 'pdf': 500, 'docx': 500}

# rh.fecha_registro es varchar en PostgreSQL; esta expresión la convierte de forma segura a timestamp.
_RH_TS = """(CASE
    WHEN BTRIM(COALESCE(rh.fecha_registro, '')) ~ '^\\d{4}-\\d{2}-\\d{2}'
        THEN BTRIM(rh.fecha_registro)::timestamp
    ELSE NULL
END)"""


class InvalidReport(ValueError):
    """Parámetros no válidos para el reporte solicitado."""


class TooManyRows(InvalidReport):
    """El archivo requiere filtros más específicos."""


def report_config(role, tipo):
    options = REPORT_TYPES.get(role, {})
    if tipo not in options:
        raise InvalidReport('Seleccione un tipo de reporte válido.')
    label, category = options[tipo]
    return {'tipo': tipo, 'label': label, 'category': category,
            'columns': COLUMNS['lecturas' if category == 'alertas' else category]}


def parse_filters(args, role):
    options = REPORT_TYPES[role]
    tipo = (args.get('tipo') or next(iter(options))).strip()
    config = report_config(role, tipo)
    params = {'tipo': tipo, 'desde': '', 'hasta': '', 'lote': '',
              'receta': '', 'resultado': '', 'usuario': '', 'evento': ''}
    for field in ('desde', 'hasta'):
        value = (args.get(field) or '').strip()
        if value:
            try:
                datetime.strptime(value, '%Y-%m-%d')
            except ValueError as exc:
                raise InvalidReport('Use fechas válidas en formato AAAA-MM-DD.') from exc
        params[field] = value
    if params['desde'] and params['hasta'] and params['desde'] > params['hasta']:
        raise InvalidReport('La fecha inicial no puede ser posterior a la fecha final.')
    for field in ('lote', 'receta') if config['category'] not in ('auditoria', 'bloqueados') else ():
        text = (args.get(field) or '').strip()
        if len(text) > 80:
            raise InvalidReport('El filtro de lote o receta no puede superar 80 caracteres.')
        params[field] = text
    resultado = (args.get('resultado') or '').strip() if config['category'] not in ('auditoria', 'bloqueados') else ''
    if resultado not in ('', 'Aprobado', 'Rechazado', 'Sin receta'):
        raise InvalidReport('La clasificación de la lectura no es válida.')
    if config['category'] in ('lecturas', 'alertas'):
        params['resultado'] = 'Rechazado' if config['category'] == 'alertas' else resultado
    if config['category'] in ('auditoria', 'bloqueados'):
        usuario = (args.get('usuario') or '').strip()
        if len(usuario) > 80:
            raise InvalidReport('La búsqueda de usuario no puede superar 80 caracteres.')
        params['usuario'] = usuario
        evento = (args.get('evento') or '').strip()
        if evento not in ('', 'Bloqueo automático', 'Desbloqueo manual'):
            raise InvalidReport('Seleccione un evento de auditoría válido.')
        if config['category'] == 'auditoria':
            params['evento'] = evento
    return params


def _like(value):
    # Escapa comodines SQL: el texto de la búsqueda se interpreta literalmente.
    return '%' + value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


def _where(filters, category):
    is_lot = category in ('lotes', 'produccion')
    time_col = 'l.fecha_inicio' if is_lot else _RH_TS
    clauses, params = [], []
    if filters['desde']:
        clauses.append(f'{time_col} >= %s::date')
        params.append(filters['desde'])
    if filters['hasta']:
        clauses.append(f"{time_col} < (%s::date + INTERVAL '1 day')")
        params.append(filters['hasta'])
    if filters['lote']:
        clauses.append("l.codigo_lote ILIKE %s ESCAPE '\\'")
        params.append(_like(filters['lote']))
    if filters['receta']:
        clauses.append("r.codigo_receta ILIKE %s ESCAPE '\\'")
        params.append(_like(filters['receta']))
    if not is_lot and filters['resultado']:
        clauses.append('rh.resultado_final = %s')
        params.append(filters['resultado'])
    return (' WHERE ' + ' AND '.join(clauses)) if clauses else '', params


def _audit_where(filters, category):
    """Sólo nombres de columnas prefijados de forma fija; valores parametrizados."""
    if category == 'auditoria':
        date_column = 'ev.fecha_evento'
        user_column = 'ev.usuario'
    else:
        date_column = 'f.ultimo_intento_fallido'
        user_column = "CONCAT_WS(' ', f.nombre, f.apellidos)"
    clauses, params = [], []
    if filters['desde']:
        clauses.append(f"{date_column} >= (%s::date::timestamp AT TIME ZONE 'America/Santiago')")
        params.append(filters['desde'])
    if filters['hasta']:
        clauses.append(f"{date_column} < ((%s::date + INTERVAL '1 day') AT TIME ZONE 'America/Santiago')")
        params.append(filters['hasta'])
    if filters['usuario']:
        clauses.append(f"({user_column} ILIKE %s ESCAPE '\\' OR "
                       f"CAST({'ev.usuario_id' if category == 'auditoria' else 'f.id'} AS text) = %s)")
        params.extend([_like(filters['usuario']), filters['usuario']])
    if category == 'auditoria' and filters['evento']:
        clauses.append('ev.evento = %s')
        params.append(filters['evento'])
    return ((' WHERE ' + ' AND '.join(clauses)) if clauses else ''), params


def _audit_query(filters, category):
    if category == 'bloqueados':
        where, values = _audit_where(filters, category)
        base = """SELECT f.id AS usuario_id, CONCAT_WS(' ', f.nombre, f.apellidos) AS usuario,
               COALESCE(r.nombre_rol, 'Sin rol') AS rol_usuario,
               f.intentos_fallidos,
               TO_CHAR(f.ultimo_intento_fallido AT TIME ZONE 'America/Santiago', 'YYYY-MM-DD HH24:MI:SS') AS ultimo_intento,
               TO_CHAR(f.bloqueado_hasta AT TIME ZONE 'America/Santiago', 'YYYY-MM-DD HH24:MI:SS') AS bloqueado_hasta
            FROM ficha_personal f LEFT JOIN roles r ON r.id = f.rol_id
            WHERE f.estado = 'Activo' AND f.bloqueado_hasta > NOW()"""
        if where:
            base += ' AND ' + where.removeprefix(' WHERE ')
        return base + ' ORDER BY f.bloqueado_hasta DESC, f.id DESC', values

    # Las tablas de auditoría son independientes de las cuentas activas: el historial
    # permanece aun si la cuenta deja de estar habilitada.
    union = """FROM (
        SELECT 'B-' || b.id::text AS evento_id, b.fecha AS fecha_evento,
               'Bloqueo automático'::text AS evento, b.usuario_id,
               COALESCE(NULLIF(CONCAT_WS(' ', f.nombre, f.apellidos), ''), 'Cuenta no disponible') AS usuario,
               COALESCE(r.nombre_rol, 'Sin rol') AS rol_usuario,
               NULL::text AS actor, NULL::text AS rol_actor,
               TO_CHAR(b.bloqueado_hasta AT TIME ZONE 'America/Santiago', 'YYYY-MM-DD HH24:MI:SS') AS bloqueado_hasta,
               b.intentos_fallidos
          FROM auditoria_bloqueos b
          LEFT JOIN ficha_personal f ON f.id = b.usuario_id
          LEFT JOIN roles r ON r.id = f.rol_id
        UNION ALL
        SELECT 'D-' || d.id::text AS evento_id, d.fecha AS fecha_evento,
               'Desbloqueo manual'::text AS evento, d.usuario_id,
               COALESCE(NULLIF(CONCAT_WS(' ', f.nombre, f.apellidos), ''), 'Cuenta no disponible') AS usuario,
               COALESCE(r.nombre_rol, 'Sin rol') AS rol_usuario,
               COALESCE(NULLIF(CONCAT_WS(' ', a.nombre, a.apellidos), ''), 'Cuenta no disponible') AS actor,
               d.rol_actor::text AS rol_actor,
               NULL::text AS bloqueado_hasta, NULL::integer AS intentos_fallidos
          FROM auditoria_desbloqueos d
          LEFT JOIN ficha_personal f ON f.id = d.usuario_id
          LEFT JOIN roles r ON r.id = f.rol_id
          LEFT JOIN ficha_personal a ON a.id = d.actor_id
    ) ev"""
    where, values = _audit_where(filters, category)
    query = """SELECT TO_CHAR(ev.fecha_evento AT TIME ZONE 'America/Santiago',
                    'YYYY-MM-DD HH24:MI:SS') AS fecha,
                    ev.evento, ev.usuario_id, ev.usuario, ev.rol_usuario,
                    ev.actor, ev.rol_actor, ev.bloqueado_hasta, ev.intentos_fallidos
          """ + union + where + ' ORDER BY ev.fecha_evento DESC, ev.evento_id DESC'
    return query, values


def _query(filters, category):
    if category in ('auditoria', 'bloqueados'):
        return _audit_query(filters, category)
    if category in ('lecturas', 'alertas', 'calidad'):
        joins = '''FROM registro_historico rh
          LEFT JOIN lote_fabricacion l ON l.id = rh.lote_id
          LEFT JOIN receta_alambre r ON r.id = rh.receta_id'''
        where, values = _where(filters, category)
        if category in ('lecturas', 'alertas'):
            select = f'''SELECT rh.id AS registro_id,
                COALESCE(TO_CHAR({_RH_TS}, 'YYYY-MM-DD HH24:MI:SS'), NULLIF(BTRIM(rh.fecha_registro), ''), '—') AS fecha,
                COALESCE(l.codigo_lote, 'Sin lote') AS lote,
                COALESCE(r.codigo_receta, 'Sin receta') AS receta,
                rh.codigo_batch AS batch, rh.angulo_medio AS angulo,
                rh.limite_min, rh.limite_max,
                rh.resultado_final AS resultado, rh.observacion'''
            order = ' ORDER BY registro_id DESC'
        else:
            select = f'''SELECT DATE({_RH_TS}) AS dia,
                COUNT(*) AS lecturas,
                COUNT(*) FILTER (WHERE rh.resultado_final = 'Aprobado') AS dentro,
                COUNT(*) FILTER (WHERE rh.resultado_final = 'Rechazado') AS fuera,
                COUNT(*) FILTER (WHERE rh.resultado_final NOT IN ('Aprobado', 'Rechazado') OR rh.resultado_final IS NULL) AS sin_clasificar,
                ROUND(100.0 * COUNT(*) FILTER (WHERE rh.resultado_final = 'Aprobado') /
                    NULLIF(COUNT(*) FILTER (WHERE rh.resultado_final IN ('Aprobado', 'Rechazado')), 0), 1) AS porcentaje'''
            order = f' GROUP BY DATE({_RH_TS}) ORDER BY dia DESC NULLS LAST'
        return select + '\n' + joins + where + order, values

    joins = '''FROM lote_fabricacion l
        LEFT JOIN receta_alambre r ON r.id = l.receta_id'''
    where, values = _where(filters, category)
    if category == 'produccion':
        select = '''SELECT DATE(l.fecha_inicio) AS dia,
           COUNT(*) AS lotes,
           COUNT(*) FILTER (WHERE LOWER(TRIM(COALESCE(l.estado, ''))) = 'activo') AS activos,
           COUNT(*) FILTER (WHERE LOWER(TRIM(COALESCE(l.estado, ''))) <> 'activo') AS otros'''
        order = ' GROUP BY DATE(l.fecha_inicio) ORDER BY dia DESC NULLS LAST'
    else:
        # Contar lecturas en una subconsulta evita multiplicar lotes por joins.
        joins += '''\n LEFT JOIN (
           SELECT lote_id, COUNT(*) AS lecturas,
              COUNT(*) FILTER (WHERE resultado_final = 'Rechazado') AS fuera
             FROM registro_historico GROUP BY lote_id
        ) hist ON hist.lote_id = l.id'''
        select = '''SELECT l.id AS lote_id, l.codigo_lote AS lote,
            TO_CHAR(l.fecha_inicio, 'YYYY-MM-DD HH24:MI:SS') AS fecha,
            COALESCE(r.codigo_receta, 'Sin receta') AS receta,
            l.estado, COALESCE(hist.lecturas, 0) AS lecturas,
            COALESCE(hist.fuera, 0) AS fuera'''
        order = ' ORDER BY l.fecha_inicio DESC, l.id DESC'
    return select + '\n' + joins + where + order, values


def get_report(conn, role, filters, limit=MAX_PREVIEW):
    """Resumen + filas reales; igual SQL y filtros para vista previa y descarga."""
    config = report_config(role, filters['tipo'])
    query, params = _query(filters, config['category'])
    # Subconsulta para contar todas las filas sin aplicar un LIMIT engañoso.
    # PostgreSQL permite ORDER BY en subconsulta, aunque el COUNT lo ignore.
    with conn.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) AS total FROM ({query}) AS report_rows', tuple(params))
        total = int((cur.fetchone() or {}).get('total') or 0)
        if limit > MAX_PREVIEW and total > limit:
            raise TooManyRows(
                f'La consulta devuelve {total} filas. El máximo para este formato es {limit}; '
                'aplique filtros más específicos.'
            )
        cur.execute(query + ' LIMIT %s', tuple(params) + (limit,))
        rows = [dict(row) for row in cur.fetchall()]
        if config['category'] in ('auditoria', 'bloqueados'):
            # Los totales corresponden a los filtros aplicados; nada se simula.
            if config['category'] == 'auditoria':
                # COUNT sobre el mismo conjunto filtrado; evita cifras que no coinciden.
                inner_sql, inner_params = _audit_query(filters, 'auditoria')
                cur.execute('SELECT COUNT(*) FILTER (WHERE evento = %s) AS bloqueos, '
                            'COUNT(*) FILTER (WHERE evento = %s) AS desbloqueos '
                            'FROM (' + inner_sql + ') AS acciones',
                            ('Bloqueo automático', 'Desbloqueo manual') + tuple(inner_params))
                metrics = dict(cur.fetchone() or {})
            else:
                metrics = {'cuentas_bloqueadas': total}
        elif config['category'] in ('lecturas', 'alertas', 'calidad'):
            where, where_params = _where(filters, config['category'])
            cur.execute('''SELECT COUNT(*) AS lecturas,
                    COUNT(*) FILTER (WHERE rh.resultado_final = 'Aprobado') AS dentro,
                    COUNT(*) FILTER (WHERE rh.resultado_final = 'Rechazado') AS fuera,
                    COUNT(*) FILTER (WHERE rh.resultado_final NOT IN ('Aprobado', 'Rechazado') OR rh.resultado_final IS NULL) AS sin_clasificar
                 FROM registro_historico rh
                 LEFT JOIN lote_fabricacion l ON l.id = rh.lote_id
                 LEFT JOIN receta_alambre r ON r.id = rh.receta_id
                 ''' + where, tuple(where_params))
            metrics = dict(cur.fetchone() or {})
            classified = int(metrics.get('dentro') or 0) + int(metrics.get('fuera') or 0)
            metrics['porcentaje'] = round(100 * int(metrics.get('dentro') or 0) / classified, 1) if classified else None
        else:
            where, where_params = _where(filters, config['category'])
            cur.execute('''SELECT COUNT(*) AS lotes,
                    COUNT(*) FILTER (WHERE LOWER(TRIM(COALESCE(l.estado, ''))) = 'activo') AS activos
                 FROM lote_fabricacion l
                 LEFT JOIN receta_alambre r ON r.id = l.receta_id
                 ''' + where, tuple(where_params))
            metrics = dict(cur.fetchone() or {})
    return {'title': config['label'], 'type': filters['tipo'],
            'category': config['category'], 'columns': config['columns'],
            'filters': filters, 'total': total, 'rows': rows,
            'preview_only': total > limit, 'metrics': metrics}