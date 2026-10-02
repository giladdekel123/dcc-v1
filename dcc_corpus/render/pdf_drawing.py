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
    kind = geometry.get("kind", "piles")
    if kind == "piles":
        piles = pile_layout(ctx.seed, geometry["piles"])
        if "Piling Layout" in ctx.doc["title"]:
            _piling_layout(c, piles, geometry)
        else:
            _general_arrangement(c, piles, geometry)
    else:
        GEOMETRY[kind](c, geometry)

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


def _heading(c, x_mm, text):
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x_mm * mm, PAGE_H - 22 * mm, text)


def _level_label(c, x, y, text):
    c.setFont("Helvetica", 8)
    c.line(x, y, x + 8 * mm, y)
    c.drawString(x + 10 * mm, y - 1 * mm, text)


def _culvert(c, g):
    """Section through the box culvert with the water main above it."""
    _heading(c, 20, "SECTION THROUGH MILL LANE CULVERT")
    top = PAGE_H - 40 * mm
    level_to_y = lambda lvl: top - (15.2 - lvl) * 22 * mm
    x0, width = 60 * mm, g["width_m"] * 22 * mm
    wall, roof = 0.25 * 22 * mm, 0.30 * 22 * mm
    invert, soffit = g["invert_level"], g["invert_level"] + g["height_m"]
    c.rect(x0 - wall, level_to_y(invert) - wall, width + 2 * wall, level_to_y(soffit) - level_to_y(invert) + wall + roof)
    c.rect(x0, level_to_y(invert), width, level_to_y(soffit) - level_to_y(invert))
    c.setDash(4, 3)
    c.line(20 * mm, level_to_y(g["road_level"]), 200 * mm, level_to_y(g["road_level"]))
    c.setDash()
    c.circle(x0 + width / 2, level_to_y(g["main_level"]) + 3.3 * mm, 3.3 * mm)
    x_labels = 210 * mm
    _level_label(c, x_labels, level_to_y(g["road_level"]), f"Road level {g['road_level']:+.2f} mAOD")
    _level_label(c, x_labels, level_to_y(g["main_level"]), f"300 mm water main invert {g['main_level']:+.2f} mAOD")
    _level_label(c, x_labels, level_to_y(soffit + 0.30), f"Culvert roof {soffit + 0.30:+.2f} mAOD")
    _level_label(c, x_labels, level_to_y(invert), f"Culvert invert {invert:+.2f} mAOD")
    c.drawString(x0, level_to_y(invert) - 12 * mm,
                 f"Box culvert {g['width_m']:.1f} m x {g['height_m']:.1f} m internal")


def _pond(c, g):
    """Plan of an attenuation pond with its outlet chamber."""
    _heading(c, 20, "POND PLAN")
    x, y, w, h = 40 * mm, PAGE_H - 150 * mm, 160 * mm, 90 * mm
    c.roundRect(x, y, w, h, 25 * mm)
    c.roundRect(x + 12 * mm, y + 12 * mm, w - 24 * mm, h - 24 * mm, 18 * mm)
    c.rect(x + w + 10 * mm, y + h / 2 - 6 * mm, 12 * mm, 12 * mm)
    c.line(x + w, y + h / 2, x + w + 10 * mm, y + h / 2)
    c.setFont("Helvetica", 9)
    c.drawString(x + 30 * mm, y + h / 2 + 4 * mm, f"Attenuation storage {g['volume_m3']:,} m3")
    c.drawString(x + 30 * mm, y + h / 2 - 3 * mm,
                 f"TWL {g['top_water_level']:+.2f} mAOD   Base {g['base_level']:+.2f} mAOD")
    c.drawString(x + w + 25 * mm, y + h / 2 - 1 * mm, f"Flow control chamber - {g['outlet_lps']:.1f} l/s")


def _layout(c, g):
    """Strip plan of the carriageway with the carrier drain and chainage ticks."""
    _heading(c, 20, f"DRAINAGE LAYOUT - SHEET {g['sheet']} OF {g['of']}")
    y, x0, x1 = PAGE_H - 90 * mm, 25 * mm, PAGE_W - 30 * mm
    c.line(x0, y + 8 * mm, x1, y + 8 * mm)
    c.line(x0, y - 8 * mm, x1, y - 8 * mm)
    c.setDash(5, 3)
    c.line(x0, y - 14 * mm, x1, y - 14 * mm)
    c.setDash()
    c.setFont("Helvetica", 8)
    c.drawString(x0, y - 20 * mm, "Carrier drain")
    c.drawString(x0, y + 12 * mm, f"Ch {g['chainage_from']}")
    c.drawRightString(x1, y + 12 * mm, f"Ch {g['chainage_to']}")
    for i in range(1, 7):
        tx = x0 + (x1 - x0) * i / 7
        c.line(tx, y + 8 * mm, tx, y + 11 * mm)


def _roundabout(c, g):
    """Roundabout plan; high friction surfacing shown hatched on the approaches."""
    _heading(c, 20, "EASTERN ROUNDABOUT PLAN")
    cx, cy, r = 120 * mm, PAGE_H - 110 * mm, 40 * mm
    c.circle(cx, cy, r)
    c.circle(cx, cy, r * 0.45)
    c.setFont("Helvetica", 8)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        c.line(cx + dx * r, cy + dy * r, cx + dx * (r + 45 * mm), cy + dy * (r + 45 * mm))
        if g["hfs"]:
            c.setLineWidth(4)
            c.line(cx + dx * r, cy + dy * r, cx + dx * (r + 20 * mm), cy + dy * (r + 20 * mm))
            c.setLineWidth(0.8)
    c.drawString(cx - 20 * mm, cy - 2 * mm, f"ICD {g['icd_m']} m")
    if g["hfs"]:
        c.drawString(cx + r + 50 * mm, cy + 5 * mm, "Heavy line: high friction surfacing, final 50 m of each approach")


def _generic(c, g):
    """Labelled views for detail drawings."""
    for i, label in enumerate(g["labels"]):
        x = 20 * mm + i * 125 * mm
        _heading(c, 20 + i * 125, label)
        c.rect(x, PAGE_H - 140 * mm, 110 * mm, 110 * mm)


GEOMETRY = {"culvert": _culvert, "pond": _pond, "layout": _layout, "roundabout": _roundabout, "generic": _generic}


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
        ("Helvetica", 8, f"Drawing number: {content.get('titleblock_doc_code', ctx.doc['doc_code'])}"),
        ("Helvetica-Bold", 9, f"Revision: {ctx.rev}     Status: {ctx.status_text(status_code)}"),
        ("Helvetica", 7, f"Scale: {content['scale']}     Date: {fmt_date(ctx.issued)}"),
        ("Helvetica", 7, f"Drawn: {content['drawn']}   Checked: {content['checked']}   Approved: {content['approved']}"),
    ]
    ty = y + TB_H - 7 * mm
    for font, size, text in lines:
        c.setFont(font, size)
        c.drawString(x + 3 * mm, ty, text)
        ty -= size * 1.6
