from __future__ import annotations

from datetime import date, datetime

from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from modules.asistencia.logic import ensure_mx


def style_sheet(worksheet, headers: list[str]) -> None:
    worksheet.append(headers)
    worksheet.freeze_panes = "A2"
    for cell in worksheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="123456")


def autofit_columns(worksheet, visible_columns: int | None = None) -> None:
    max_column = visible_columns or worksheet.max_column
    max_lengths = [0] * max_column
    for row in worksheet.iter_rows(min_col=1, max_col=max_column, values_only=True):
        for index, value in enumerate(row):
            length = len(str(value)) if value else 0
            if length > max_lengths[index]:
                max_lengths[index] = length
    for index, length in enumerate(max_lengths, start=1):
        column_letter = get_column_letter(index)
        worksheet.column_dimensions[column_letter].width = min(length + 2, 36)


def format_date(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else ""


def format_datetime(value: datetime | None) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return ensure_mx(value).strftime("%d/%m/%Y %H:%M")
    return str(value)
