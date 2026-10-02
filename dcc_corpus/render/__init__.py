from dcc_corpus.render import (docx_documents, pdf_document, pdf_drawing, xlsx_boq, xlsx_programme,
                               xlsx_schedule, xlsx_table)

RENDERERS = {
    "pdf_drawing": pdf_drawing.render,
    "pdf_report": pdf_document.render_report,
    "pdf_certificate": pdf_document.render_certificate,
    "docx_rfi": docx_documents.render_rfi,
    "docx_letter": docx_documents.render_letter,
    "docx_minutes": docx_documents.render_minutes,
    "docx_submittal": docx_documents.render_submittal,
    "xlsx_schedule": xlsx_schedule.render,
    "xlsx_boq": xlsx_boq.render,
    "xlsx_programme": xlsx_programme.render,
    "xlsx_table": xlsx_table.render,
}
