"""Construction programme spreadsheet (activity list with dates)."""

from pathlib import Path

from dcc_corpus.render.common import RenderContext
from dcc_corpus.render.xlsx_common import bold_row, new_workbook, save, write_header

COLUMNS = ["ID", "Activity", "WBS", "Start", "Finish", "Duration (days)"]


def render(path: Path, ctx: RenderContext) -> None:
    c = ctx.content
    wb = new_workbook(ctx, "Programme")
    ws = wb.active
    write_header(ws, ctx)
    for note in c.get("notes", []):
        ws.append(["Note", note])
    ws.append([])
    bold_row(ws, COLUMNS)
    for activity_id, name, wbs, start, finish in c["activities"]:
        ws.append([activity_id, name, wbs, start, finish, (finish - start).days + 1])
        for cell in ws[ws.max_row][3:5]:
            cell.number_format = "DD/MM/YYYY"
    for col, width in zip("ABCDEF", [7, 44, 6, 12, 12, 15]):
        ws.column_dimensions[col].width = width
    save(wb, path, ctx)
