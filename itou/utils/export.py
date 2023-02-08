import io

import openpyxl
import xlsx_streaming
from django import http
from django.utils import timezone


def generate_excel_sheet(headers, rows):
    workbook = openpyxl.Workbook()
    sheet = workbook.active

    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    dimension = sheet.calculate_dimension()
    sheet.auto_filter.ref = dimension

    return workbook


def _generate_excel_template(headers):
    template = generate_excel_sheet(
        headers,
        [["Default" for _header in headers]],  # Force the type of each column to text
    )
    buffer = io.BytesIO()
    openpyxl.writer.excel.save_workbook(template, buffer)
    buffer.seek(0)
    return buffer


def to_streaming_response(queryset, filename, headers, serializer, with_time=False):
    """Generate a HTTP Streaming response with a XLSX file"""

    xlsx_streaming.set_export_timezone(timezone.get_default_timezone())
    openxml_mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    template = _generate_excel_template(headers)
    stream = xlsx_streaming.stream_queryset_as_xlsx(queryset, template, serializer=serializer)
    response = http.StreamingHttpResponse(stream, content_type=openxml_mimetype)
    if with_time:
        now = timezone.now().isoformat(timespec="seconds").replace(":", "-")
        filename = f"{filename}-{now}"
    response["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
    return response
