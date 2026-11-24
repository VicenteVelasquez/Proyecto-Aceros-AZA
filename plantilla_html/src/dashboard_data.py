"""Consultas reales para dashboards de Aceros AZA.

Los conteos de lotes salen de lote_fabricacion; las lecturas y sus resultados,
de registro_historico. No se infieren toneladas, personas conectadas ni
'eficiencia industrial' a partir de esos registros.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo('America/Santiago')

# fecha_registro es varchar en registro_historico; se convierte de forma segura a timestamp.
_RH_TS = """(CASE
    WHEN BTRIM(COALESCE(fecha_registro, '')) ~ '^\\d{4}-\\d{2}-\\d{2}'
        THEN BTRIM(fecha_registro)::timestamp
    ELSE NULL
END)"""


def _count(cursor, statement):
    cursor.execute(statement)
    return int((cursor.fetchone() or {}).get('total') or 0)


def _reading_summary(cursor):
    cursor.execute("""
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE resultado_final = 'Aprobado') AS within_count,
               COUNT(*) FILTER (WHERE resultado_final = 'Rechazado') AS outside
          FROM registro_historico;
    """)
    row = cursor.fetchone() or {}
    within, outside = int(row.get('within_count') or 0), int(row.get('outside') or 0)
    classified = within + outside
    return {
        'readings': int(row.get('total') or 0),
        'within_tolerance': round(within * 100.0 / classified, 1) if classified else None,
        'alerts': outside,
        'classified': classified,
    }


def _date_label(day):
    return day.strftime('%d/%m') if hasattr(day, 'strftime') else str(day or 'Sin fecha')


def _freshness():
    return datetime.now(TZ).strftime('%d/%m/%Y %H:%M:%S')


def get_supervisor_dashboard_data(conn):
    """Devuelve datos para las tres pestañas del dashboard Supervisor.

    Las fechas de SQL usan el calendario de la sesión de PostgreSQL.
    Si se requiere precisión de turno/cambio de día, configurar su zona horaria.
    """
    with conn.cursor() as cur:
        active_lots = _count(cur, """
            SELECT COUNT(*) AS total FROM lote_fabricacion
             WHERE LOWER(TRIM(COALESCE(estado, ''))) = 'activo';
        """)
        reading_stats = _reading_summary(cur)

        # Histórico de lotes, no registros angulares (últimos 7 días calendario).
        cur.execute("""
            SELECT DATE(fecha_inicio) AS day, COUNT(*) AS total
              FROM lote_fabricacion
             WHERE fecha_inicio >= CURRENT_DATE - INTERVAL '6 days'
             GROUP BY DATE(fecha_inicio)
             ORDER BY day DESC;
        """)
        raw_production = cur.fetchall()
        maximum = max((int(row.get('total') or 0) for row in raw_production), default=0)
        production_by_day = [
            {'day': _date_label(row.get('day')),
             'count': int(row.get('total') or 0),
             'bar_width': round(int(row.get('total') or 0) * 100 / maximum) if maximum else 0}
            for row in raw_production
        ]

        # Denominador: solo las lecturas clasificadas Aprobado/Rechazado.
        cur.execute(f"""
            SELECT DATE({_RH_TS}) AS day,
                   COUNT(*) FILTER (WHERE resultado_final = 'Aprobado') AS within_count,
                   COUNT(*) FILTER (WHERE resultado_final IN ('Aprobado', 'Rechazado')) AS classified
              FROM registro_historico
             WHERE {_RH_TS} >= CURRENT_DATE - INTERVAL '6 days'
             GROUP BY DATE({_RH_TS})
             ORDER BY day DESC NULLS LAST;
        """)
        quality_by_day = []
        for row in cur.fetchall():
            classified = int(row.get('classified') or 0)
            within = int(row.get('within_count') or 0)
            quality_by_day.append({
                'day': _date_label(row.get('day')),
                'percentage': round(within * 100.0 / classified, 1) if classified else None,
            })

        # Evita mezclar lotes y lecturas (JOIN que multiplica las filas).
        # El porcentaje es tasa de lecturas dentro de tolerancia, NO eficiencia.
        cur.execute("""
            SELECT f.id,
                   TRIM(CONCAT_WS(' ', f.nombre, f.apellidos)) AS name,
                   COALESCE(l.lots_count, 0) AS lots_count,
                   COALESCE(m.readings_count, 0) AS readings_count,
                   COALESCE(m.classified, 0) AS classified,
                   COALESCE(m.within_count, 0) AS within_count
              FROM ficha_personal f
              JOIN roles r ON r.id = f.rol_id
              LEFT JOIN (
                  SELECT personal_id, COUNT(*) AS lots_count
                    FROM lote_fabricacion GROUP BY personal_id
              ) l ON l.personal_id = f.id
              LEFT JOIN (
                  SELECT operador_id,
                         COUNT(*) AS readings_count,
                         COUNT(*) FILTER (WHERE resultado_final IN ('Aprobado', 'Rechazado')) AS classified,
                         COUNT(*) FILTER (WHERE resultado_final = 'Aprobado') AS within_count
                    FROM registro_historico GROUP BY operador_id
              ) m ON m.operador_id = f.id
             WHERE LOWER(TRIM(r.nombre_rol)) LIKE '%operador%'
             ORDER BY f.nombre, f.apellidos, f.id
             LIMIT 50;
        """)
        operators_stats = []
        for row in cur.fetchall():
            classified = int(row.get('classified') or 0)
            within = int(row.get('within_count') or 0)
            operators_stats.append({
                'name': row.get('name') or f"Operador #{row['id']}",
                'lots_count': int(row.get('lots_count') or 0),
                'readings_count': int(row.get('readings_count') or 0),
                'within_tolerance': round(within * 100.0 / classified, 1) if classified else None,
            })

        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE fecha_inicio >= CURRENT_DATE
                                    AND fecha_inicio < CURRENT_DATE + INTERVAL '1 day') AS day_total,
                   COUNT(*) FILTER (WHERE fecha_inicio >= DATE_TRUNC('week', CURRENT_DATE)) AS week_total,
                   COUNT(*) FILTER (WHERE fecha_inicio >= DATE_TRUNC('month', CURRENT_DATE)) AS month_total
              FROM lote_fabricacion;
        """)
        period = cur.fetchone() or {}

        cur.execute("""
            SELECT l.codigo_lote AS code,
                   TO_CHAR(l.fecha_inicio, 'YYYY-MM-DD HH24:MI') AS date_label,
                   COALESCE(r.codigo_receta, 'Sin receta') AS recipe,
                   COALESCE(l.estado, 'Sin estado') AS status
              FROM lote_fabricacion l
              LEFT JOIN receta_alambre r ON r.id = l.receta_id
             ORDER BY l.fecha_inicio DESC, l.id DESC
             LIMIT 5;
        """)
        lots = []
        for row in cur.fetchall():
            status = row.get('status') or 'Sin estado'
            lots.append({
                'code': row.get('code') or 'Sin código',
                'date_label': row.get('date_label') or 'Sin fecha',
                'recipe': row.get('recipe') or 'Sin receta',
                'status': status,
                'style': 'bg-success' if status.casefold() == 'activo' else 'bg-secondary',
            })

    dashboard = {
        'period': 'Datos históricos',
        'updated_at': _freshness(),
        'summary': {'active_lots': active_lots, **reading_stats},
        'production_by_day': production_by_day,
        'quality_by_day': quality_by_day,
        'operators_stats': operators_stats,
        'production_day_total': int(period.get('day_total') or 0),
        'production_week_total': int(period.get('week_total') or 0),
        'production_month_total': int(period.get('month_total') or 0),
    }
    return {'dashboard': dashboard, 'lots': lots}


def get_admin_dashboard_data(conn):
    """Métricas administrativas reales, sin simular usuarios 'en línea'."""
    with conn.cursor() as cur:
        lots_total = _count(cur, 'SELECT COUNT(*) AS total FROM lote_fabricacion;')
        reading_stats = _reading_summary(cur)
        operators_active = _count(cur, """
            SELECT COUNT(*) AS total
              FROM ficha_personal f
              JOIN roles r ON r.id = f.rol_id
             WHERE LOWER(TRIM(COALESCE(f.estado, ''))) = 'activo'
               AND LOWER(TRIM(r.nombre_rol)) LIKE '%operador%';
        """)
    return {'admin_stats': {
        'lots_total': lots_total,
        'within_tolerance': reading_stats['within_tolerance'],
        'classified_readings': reading_stats['classified'],
        'readings_total': reading_stats['readings'],
        'alerts': reading_stats['alerts'],
        'operators_active': operators_active,
        'updated_at': _freshness(),
    }}