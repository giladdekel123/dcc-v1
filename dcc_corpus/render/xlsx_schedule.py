"""Pile schedule spreadsheet."""

from pathlib import Path

from dcc_corpus.render.common import RenderContext, pile_layout
from dcc_corpus.render.xlsx_common import bold_row, new_workbook, save, write_header

COLUMNS = ["Pile ref", "Easting", "Northing", "Existing ground (mAOD)", "Cut-off level (mAOD)",
           "Toe level (mAOD)", "Length (m)", "Diameter (mm)"]


def render(path: Path, ctx: RenderContext) -> None:
    g = ctx.content["geometry"]
    wb = new_workbook(ctx, "Pile Schedule")
    ws = wb.active
    write_header(ws, ctx)
    bold_row(ws, COLUMNS)
    length = round(g["cutoff_level"] - g["toe_level"], 2)
    for p in pile_layout(ctx.seed, g["piles"]):
        ws.append([p["ref"], p["easting"], p["northing"], p["ground_level"],
                   g["cutoff_level"], g["toe_level"], length, g["pile_diameter_mm"]])
    for col, width in zip("ABCDEFGH", [10, 14, 14, 22, 20, 17, 11, 13]):
        ws.column_dimensions[col].width = width
    save(wb, path, ctx)
