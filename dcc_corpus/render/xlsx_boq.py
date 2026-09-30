"""Bill of quantities or priced variation spreadsheet."""

from pathlib import Path

from dcc_corpus.render.common import RenderContext
from dcc_corpus.render.xlsx_common import bold_row, new_workbook, save, write_header

COLUMNS = ["Item", "Description", "Unit", "Quantity", "Rate", "Amount"]


def render(path: Path, ctx: RenderContext) -> None:
    c = ctx.content
    wb = new_workbook(ctx, "BoQ")
    ws = wb.active
    write_header(ws, ctx, rev_shown=c.get("header_rev"))
    bold_row(ws, [f"{c['heading']} ({c['currency']})"])
    bold_row(ws, COLUMNS)
    total = 0.0
    for ref, description, unit, quantity, rate in c["items"]:
        amount = round(quantity * rate, 2)
        total += amount
        ws.append([ref, description, unit, quantity, rate, amount])
    ws.append([])
    bold_row(ws, ["", "Total", "", "", "", round(total, 2)])
    for col, width in zip("ABCDEF", [8, 58, 7, 11, 11, 13]):
        ws.column_dimensions[col].width = width
    save(wb, path, ctx)
