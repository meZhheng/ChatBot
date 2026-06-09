from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


templates = Jinja2Templates(directory="app/templates")
router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def homepage(request: Request):
    return templates.TemplateResponse(request, "index.html")


@router.get("/admin/rag", response_class=HTMLResponse)
def rag_admin_page(request: Request):
    return templates.TemplateResponse(request, "admin_rag.html")


@router.get("/admin/faq", response_class=HTMLResponse)
def faq_admin_page(request: Request):
    return templates.TemplateResponse(request, "admin_faq.html")
