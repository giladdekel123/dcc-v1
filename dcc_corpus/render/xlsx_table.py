"""Generic schedule spreadsheet: a document header, optional notes, then a table of columns and rows."""

from pathlib import Path

from dcc_corpus.render.common import RenderContext
from dcc_corpus.render.xlsx_common import bold_row, new_workbook, save, write_header


def render(path: Path, ctx: RenderContext) -> None:
    c = ctx.content
    wb = new_workbook(ctx, c["sheet_title"])
    ws = wb.active
    write_header(ws, ctx, rev_shown=c.get("header_rev"))
    for note in c.get("notes", []):
        ws.append(["Note", note])
    if c.get("notes"):
        ws.append([])
    bold_row(ws, c["columns"])
    for row in c["rows"]:
        ws.append(row)
    for index, column in enumerate(c["columns"]):
        width = max(len(str(column)), *(len(str(row[index])) for row in c["rows"]))
        ws.column_dimensions[chr(ord("A") + index)].width = min(width + 2, 50)
    save(wb, path, ctx)
