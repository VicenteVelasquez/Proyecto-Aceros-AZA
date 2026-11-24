"""Exportación de reportes de PostgreSQL: CSV, Excel, PDF y Word.

Se usa la misma instantánea de filas/columnas que la vista previa filtrada.
"""
import csv
import io
from datetime import date, datetime
from decimal import Decimal

MIME = {
    'csv': 'text/csv; charset=utf-8',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'pdf': 'application/pdf',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}


def _visible(value):
    if value is None:
        return ''
    if isinstance(value, (date, datetime)):
        return value.isoformat(sep=' ') if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _metadata(report):
    f = report['filters']
    result = [
        ('Tipo de informe', report['title']),
        ('Fecha inicial', f.get('desde') or 'Sin filtro'),
        ('Fecha final', f.get('hasta') or 'Sin filtro'),
    ]
    if report['category'] in ('auditoria', 'bloqueados'):
        result.append(('Usuario afectado', f.get('usuario') or 'Todos'))
        if report['category'] == 'auditoria':
            result.append(('Evento', f.get('evento') or 'Todos'))
    else:
        result.extend([
            ('Lote contiene', f.get('lote') or 'Sin filtro'),
            ('Receta contiene', f.get('receta') or 'Sin filtro'),
            ('Resultado', f.get('resultado') or 'Todos'),
        ])
    result.append(('Filas del informe', report['total']))
    return result


def _safe_spreadsheet(value):
    """Evita ejecución de fórmulas al abrir CSV en Excel o LibreOffice."""
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return _visible(value)


def _csv(report):
    out = io.StringIO(newline='')
    writer = csv.writer(out, delimiter=';')
    writer.writerow([label for _, label in report['columns']])
    for row in report['rows']:
        writer.writerow([_safe_spreadsheet(row.get(key)) for key, _ in report['columns']])
    return out.getvalue().encode('utf-8-sig')


def _xlsx(report):
    import xlsxwriter
    stream = io.BytesIO()
    wb = xlsxwriter.Workbook(stream, {'in_memory': True})
    wb.set_properties({'title': report['title'], 'author': 'Aceros AZA — ES3'})
    title_fmt = wb.add_format({'bold': True, 'font_size': 15, 'font_color': '#173B26'})
    header_fmt = wb.add_format({'bold': True, 'font_color': '#FFFFFF', 'bg_color': '#1A6B3A', 'border': 1})
    num_fmt = wb.add_format({'num_format': '0.00'})
    summary = wb.add_worksheet('Resumen')
    summary.set_column('A:A', 24)
    summary.set_column('B:B', 36)
    summary.write(0, 0, report['title'], title_fmt)
    for i, (label, value) in enumerate(_metadata(report), 2):
        summary.write_string(i, 0, label)
        if isinstance(value, (int, float)):
            summary.write_number(i, 1, value)
        else:
            summary.write_string(i, 1, _visible(value))
    offset = 11
    summary.write_string(offset, 0, 'Indicadores sobre datos filtrados', header_fmt)
    for i, (label, val) in enumerate(report['metrics'].items(), offset + 1):
        summary.write_string(i, 0, label.replace('_', ' ').capitalize())
        if isinstance(val, (int, float, Decimal)):
            summary.write_number(i, 1, float(val))
        else:
            summary.write_string(i, 1, 'Sin datos' if val is None else str(val))
    data = wb.add_worksheet('Datos')
    headers = report['columns']
    for col, (_, label) in enumerate(headers):
        data.write_string(0, col, label, header_fmt)
        data.set_column(col, col, min(35, max(14, len(label) + 3)))
    for row_num, row in enumerate(report['rows'], start=1):
        for col_num, (key, _) in enumerate(headers):
            value = row.get(key)
            if isinstance(value, (float, int, Decimal)) and not isinstance(value, bool):
                data.write_number(row_num, col_num, float(value), num_fmt if isinstance(value, (float, Decimal)) else None)
            else:
                data.write_string(row_num, col_num, _visible(value))
    data.freeze_panes(1, 0)
    data.autofilter(0, 0, max(1, len(report['rows'])), len(headers) - 1)
    data.set_landscape()
    wb.close()
    return stream.getvalue()


def _pdf(report):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A3, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
    from xml.sax.saxutils import escape

    stream = io.BytesIO()
    doc = SimpleDocTemplate(stream, pagesize=landscape(A3), rightMargin=24,
                            leftMargin=24, topMargin=28, bottomMargin=28)
    styles = {
        'title': ParagraphStyle('aza-title', fontName='Helvetica-Bold', fontSize=14, leading=18),
        'normal': ParagraphStyle('aza-body', fontName='Helvetica', fontSize=8, leading=10),
        'small': ParagraphStyle('aza-cell', fontName='Helvetica', fontSize=6, leading=8),
        'head': ParagraphStyle('aza-cell-head', fontName='Helvetica-Bold', fontSize=6, leading=8,
                               textColor=colors.white, alignment=TA_CENTER),
    }
    elements = [Paragraph(escape(report['title']), styles['title']), Spacer(1, 7)]
    elements.extend(Paragraph(escape(f'{label}: {_visible(value)}'), styles['normal']) for label, value in _metadata(report))
    elements.append(Spacer(1, 10))
    elements.append(Paragraph('Indicadores: ' + ', '.join(
        f"{k.replace('_', ' ')}: {_visible(v) if v is not None else 'Sin datos'}"
        for k, v in report['metrics'].items()), styles['normal']))
    elements.append(Spacer(1, 10))
    columns = report['columns']
    grid = [[Paragraph(escape(label), styles['head']) for _, label in columns]]
    for item in report['rows']:
        grid.append([Paragraph(escape(_visible(item.get(key))), styles['small']) for key, _ in columns])
    widths = [85] * len(columns)
    total_width = landscape(A3)[0] - 48
    widths = [total_width / len(columns)] * len(columns)
    table = Table(grid, colWidths=widths, repeatRows=1, hAlign='LEFT')
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1A6B3A')),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#C8D5CA')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F1F8F2')]),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 8))
    elements.append(Paragraph('Fuente: registros almacenados en PostgreSQL/Supabase. '
                'La auditoría contiene eventos persistidos; no incorpora contraseñas ni tokens.', styles['normal']))
    doc.build(elements)
    return stream.getvalue()


def _docx(report):
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.shared import Inches, Pt

    doc = Document()
    section = doc.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = Inches(11.7), Inches(8.3)
    section.left_margin = section.right_margin = Inches(0.55)
    doc.add_heading(report['title'], 0)
    for label, value in _metadata(report):
        doc.add_paragraph(f'{label}: {_visible(value)}')
    doc.add_heading('Indicadores', level=2)
    for k, v in report['metrics'].items():
        doc.add_paragraph(f"{k.replace('_', ' ').capitalize()}: {_visible(v) if v is not None else 'Sin datos'}")
    doc.add_heading('Registros', level=2)
    table = doc.add_table(rows=1, cols=len(report['columns']))
    table.style = 'Table Grid'
    for cell, (_, label) in zip(table.rows[0].cells, report['columns']):
        cell.text = label
    for row in report['rows']:
        cells = table.add_row().cells
        for cell, (key, _) in zip(cells, report['columns']):
            cell.text = _visible(row.get(key))
    for row in table.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(7)
    doc.add_paragraph('Fuente: PostgreSQL/Supabase. Los resultados se basan en los registros existentes y sus filtros.')
    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()


def export(report, formato):
    exports = {'csv': _csv, 'xlsx': _xlsx, 'pdf': _pdf, 'docx': _docx}
    if formato not in exports:
        raise ValueError('Formato de exportación no admitido.')
    return exports[formato](report), MIME[formato]
