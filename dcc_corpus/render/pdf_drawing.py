"""Simplified drawing sheet: geometry, notes, revision table and title block."""

from pathlib import Path
from textwrap import wrap

from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from dcc_corpus.render.common import RenderContext, fmt_date, pile_layout

PAGE_W, PAGE_H = landscape(A3)
TB_W, TB_H = 150 * mm, 80 * mm
TB_X, TB_Y = PAGE_W - 10 * mm - TB_W, 10 * mm


def render(path: Path, ctx: RenderContext) -> None:
    c = canvas.Canvas(str(path), pagesize=(PAGE_W, PAGE_H))
    c.setTitle(f"{ctx.doc['doc_code']} {ctx.rev} {ctx.doc['title']}")
    c.setAuthor(ctx.org_name(ctx.code.originator))
    c.setSubject(ctx.project["project"]["name"])
    c.setLineWidth(0.8)
    c.rect(10 * mm, 10 * mm, PAGE_W - 20 * mm, PAGE_H - 20 * mm)

    geometry = ctx.content["geometry"]
    piles = pile_layout(ctx.seed, geometry["piles"])
    if "Piling Layout" in ctx.doc["title"]:
        _piling_layout(c, piles, geometry)
    else:
        _general_arrangement(c, piles, geometry)

    _notes(c, ctx.content.get("notes", []))
    _revision_table(c, ctx)
    _title_block(c, ctx)
    c.showPage()
    c.save()


def _general_arrangement(c, piles, g):
    c.setFont("Helvetica-Bold", 11)
    c.drawString(20 * mm, PAGE_H - 22 * mm, "PLAN ON EAST ABUTMENT")
    ox, oy, s = 30 * mm, PAGE_H - 120 * mm, 9 * mm
    c.rect(ox - 1.5 * s, oy - 1.5 * s, 3 * 2.7 * s + 3 * s, 2.7 * s + 3 * s)
    _pile_circles(c, piles, ox, oy, s, g["pile_diameter_mm"])
    c.setFont("Helvetica", 8)
    c.drawString(ox - 1.5 * s, oy - 1.5 * s - 6 * mm, "Pile cap 11.1 m x 5.7 m.")

    c.setFont("Helvetica-Bold", 11)
    c.drawString(140 * mm, PAGE_H - 22 * mm, "ELEVATION ON EAST ABUTMENT")
    ex, top = 150 * mm, PAGE_H - 35 * mm
    level_to_y = lambda lvl: top - (15.5 - lvl) * 4.5 * mm
    c.rect(ex, level_to_y(12.75), 80 * mm, level_to_y(14.35) - level_to_y(12.75))  # pile cap
    for i in range(4):
        x = ex + 8 * mm + i * 20 * mm
        c.rect(x, level_to_y(g["toe_level"]), 5 * mm, level_to_y(g["cutoff_level"]) - level_to_y(g["toe_level"]))
    c.setFont("Helvetica", 8)
    labels = [
        (14.2, "Existing ground approx. +14.2 mAOD"),
        (g["cutoff_level"], f"Pile cut-off level {g['cutoff_level']:+.2f} mAOD"),
        (g["toe_level"], f"Pile toe level {g['toe_level']:+.2f} mAOD"),
    ]
    for level, text in labels:
        y = level_to_y(level)
        c.line(ex + 82 * mm, y, ex + 90 * mm, y)
        c.drawString(ex + 92 * mm, y - 1 * mm, text)
    length = g["cutoff_level"] - g["toe_level"]
    c.drawString(ex, level_to_y(g["toe_level"]) - 8 * mm,
                 f"{g['piles']} No. {g['pile_diameter_mm']} mm dia. bored piles, {length:.1f} m long")


def _piling_layout(c, piles, g):
    c.setFont("Helvetica-Bold", 11)
    c.drawString(20 * mm, PAGE_H - 22 * mm, "EAST ABUTMENT PILING LAYOUT")
    ox, oy, s = 35 * mm, PAGE_H - 110 * mm, 14 * mm
    _pile_circles(c, piles, ox, oy, s, g["pile_diameter_mm"], label=True)

    c.setFont("Helvetica-Bold", 10)
    c.drawString(200 * mm, PAGE_H - 22 * mm, "PILE SETTING-OUT")
    headers = ["Pile", "Easting", "Northing", "Cut-off (mAOD)", "Toe (mAOD)"]
    widths = [15, 30, 30, 30, 25]
    y = PAGE_H - 32 * mm
    c.setFont("Helvetica-Bold", 8)
    _row(c, 200 * mm, y, headers, widths)
    c.setFont("Helvetica", 8)
    for p in piles:
        y -= 6 * mm
        _row(c, 200 * mm, y, [p["ref"], f"{p['easting']:.3f}", f"{p['northing']:.3f}",
                              f"{g['cutoff_level']:+.2f}", f"{g['toe_level']:+.2f}"], widths)


def _pile_circles(c, piles, ox, oy, s, diameter_mm, label=False):
    r = diameter_mm / 1000 / 2 * s
    c.setFont("Helvetica", 7)
    for p in piles:
        x, y = ox + p["x"] * s, oy + p["y"] * s
        c.circle(x, y, r)
        c.line(x - r * 1.4, y, x + r * 1.4, y)
        c.line(x, y - r * 1.4, x, y + r * 1.4)
        if label:
            c.drawString(x + r + 1 * mm, y + r, p["ref"])


def _row(c, x, y, cells, widths):
    for cell, w in zip(cells, widths):
        c.drawString(x, y, cell)
        x += w * mm


def _notes(c, notes):
    x, y = 20 * mm, 88 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x, y, "NOTES")
    c.setFont("Helvetica", 8)
    for i, note in enumerate(notes, 1):
        for j, line in enumerate(wrap(note, 110)):
            y -= 4.5 * mm
            c.drawString(x, y, (f"{i}. " if j == 0 else "    ") + line)


def _revision_table(c, ctx):
    rows = list(reversed(ctx.history))
    height = (len(rows) + 1) * 6 * mm
    x, y = TB_X, TB_Y + TB_H
    c.rect(x, y, TB_W, height)
    c.setFont("Helvetica-Bold", 7)
    top = y + height
    _row(c, x + 2 * mm, top - 4.5 * mm, ["Rev", "Date", "Description"], [15, 28, 100])
    c.setFont("Helvetica", 7)
    for i, (rev, when, description) in enumerate(rows, 1):
        _row(c, x + 2 * mm, top - 4.5 * mm - i * 6 * mm, [rev, when.strftime("%d/%m/%Y"), description], [15, 28, 100])


def _title_block(c, ctx):
    x, y = TB_X, TB_Y
    c.rect(x, y, TB_W, TB_H)
    content = ctx.content
    status_code = content.get("titleblock_status", ctx.status)
    lines = [
        ("Helvetica", 7, f"Client: {ctx.org_name('NCC')}"),
        ("Helvetica", 7, f"Designer: {ctx.org_name(ctx.code.originator)}"),
        ("Helvetica-Bold", 9, ctx.project["project"]["name"]),
        *[("Helvetica-Bold", 10, t) for t in wrap(ctx.doc["title"], 48)],
        ("Helvetica", 8, f"Drawing number: {ctx.doc['doc_code']}"),
        ("Helvetica-Bold", 9, f"Revision: {ctx.rev}     Status: {ctx.status_text(status_code)}"),
        ("Helvetica", 7, f"Scale: {content['scale']}     Date: {fmt_date(ctx.issued)}"),
        ("Helvetica", 7, f"Drawn: {content['drawn']}   Checked: {content['checked']}   Approved: {content['approved']}"),
    ]
    ty = y + TB_H - 7 * mm
    for font, size, text in lines:
        c.setFont(font, size)
        c.drawString(x + 3 * mm, ty, text)
        ty -= size * 1.6
