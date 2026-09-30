"""Text PDFs: reports and certificates."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from dcc_corpus.render.common import RenderContext, fmt_date

STYLES = getSampleStyleSheet()
GRID = TableStyle([
    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ("FONTSIZE", (0, 0), (-1, -1), 8),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
])
HEADER_GRID = TableStyle([*GRID.getCommands(), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")])


def _document(path: Path, ctx: RenderContext) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        str(path), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=20 * mm, bottomMargin=20 * mm,
        title=f"{ctx.doc['doc_code']} {ctx.rev} {ctx.doc['title']}",
        author=ctx.org_name(ctx.code.originator), subject=ctx.project["project"]["name"],
    )


def _cover(ctx: RenderContext) -> list:
    rows = [
        ["Project", ctx.project["project"]["name"]],
        ["Document", ctx.doc["doc_code"]],
        ["Revision", ctx.rev],
        ["Status", ctx.status_text()],
        ["Date", fmt_date(ctx.issued)],
        ["Originator", ctx.org_name(ctx.code.originator)],
    ]
    history = [["Rev", "Date", "Description"]] + [[r, d.strftime("%d/%m/%Y"), desc] for r, d, desc in ctx.history]
    return [
        Paragraph(ctx.org_name(ctx.code.originator), STYLES["Normal"]),
        Paragraph(ctx.doc["title"], STYLES["Title"]),
        Table(rows, colWidths=[35 * mm, 125 * mm], style=GRID),
        Spacer(1, 4 * mm),
        Table(history, colWidths=[15 * mm, 25 * mm, 120 * mm], style=HEADER_GRID),
        Spacer(1, 8 * mm),
    ]


def render_report(path: Path, ctx: RenderContext) -> None:
    story = _cover(ctx)
    for section in ctx.content["sections"]:
        story.append(Paragraph(section["heading"], STYLES["Heading2"]))
        story += [Paragraph(p.strip(), STYLES["BodyText"]) for p in section.get("paragraphs", [])]
        if "table" in section:
            t = section["table"]
            rows = [t["columns"]] + [[f"{v:.2f}" if isinstance(v, float) else str(v) for v in row] for row in t["rows"]]
            story += [Spacer(1, 2 * mm), Table(rows, style=HEADER_GRID), Spacer(1, 2 * mm)]
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(f"Prepared by: {ctx.person_line(ctx.doc['owner'])}", STYLES["Normal"]))
    _document(path, ctx).build(story)


def render_certificate(path: Path, ctx: RenderContext) -> None:
    c = ctx.content
    story = _cover(ctx)
    story += [
        Paragraph("Design and Check Certificate", STYLES["Heading2"]),
        Table([["Structure", c["structure"]], ["Check category", c["category"]]],
              colWidths=[35 * mm, 125 * mm], style=GRID),
        Spacer(1, 4 * mm),
        Paragraph("Documents checked", STYLES["Heading3"]),
        Table([["Document", "Revision"]] + [list(d) for d in c["checked_documents"]],
              colWidths=[80 * mm, 25 * mm], style=HEADER_GRID),
        Spacer(1, 4 * mm),
        Paragraph(c["statement"].strip(), STYLES["BodyText"]),
        Spacer(1, 8 * mm),
        Paragraph(f"Checker: {ctx.person_line(c['checker'])}", STYLES["Normal"]),
        Paragraph(f"Designer: {ctx.person_line(c['designer'])}", STYLES["Normal"]),
    ]
    _document(path, ctx).build(story)
