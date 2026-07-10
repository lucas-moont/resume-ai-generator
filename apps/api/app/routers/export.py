from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.domain.schemas import PdfExportRequest
from app.services.pdf_export import render_resume_pdf

router = APIRouter()


@router.post("/api/export/pdf")
async def export_pdf(body: PdfExportRequest):
    try:
        pdf_bytes = await render_resume_pdf(body.resume, body.template)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF failed: {e}") from e
    fname = f"curriculo-{datetime.now().strftime('%Y%m%d-%H%M')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
