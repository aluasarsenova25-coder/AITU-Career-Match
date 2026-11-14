from datetime import date, datetime

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from fastapi.templating import Jinja2Templates

from database import EmployerProfile, ModerationLog, SessionLocal, User, Vacancy

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def get_admin(request, db):
    """Returns the admin user or None. The role is always checked on the server."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.get(User, user_id)
    if not user or user.role != "admin" or user.is_blocked:
        return None
    return user


def log_action(db, admin, action, target_type, target_id, reason=None):
    db.add(ModerationLog(admin_id=admin.id, action=action, target_type=target_type,
                         target_id=target_id, reason=reason))


@router.get("/admin")
def admin_companies(request: Request):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        companies = db.query(EmployerProfile).order_by(
            EmployerProfile.verified, EmployerProfile.id.desc()).all()
        rows = [{
            "company": c,
            "email": c.user.email if c.user else "",
            "vacancy_count": db.query(Vacancy).filter_by(employer_id=c.id).count(),
        } for c in companies]
        return templates.TemplateResponse(request, "admin_companies.html", {"rows": rows})
    finally:
        db.close()


def set_verified(request, company_id, value):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        company = db.get(EmployerProfile, company_id)
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        if company.verified != value:
            company.verified = value
            log_action(db, admin, "verify_company" if value else "unverify_company",
                       "company", company.id)
            db.commit()
        return RedirectResponse("/admin", status_code=303)
    finally:
        db.close()


@router.post("/admin/company/{company_id}/verify")
def verify_company(request: Request, company_id: int):
    return set_verified(request, company_id, True)


@router.post("/admin/company/{company_id}/unverify")
def unverify_company(request: Request, company_id: int):
    return set_verified(request, company_id, False)

@router.get("/admin/vacancies")
def admin_vacancies(request: Request, msg: str = ""):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        pending = db.query(Vacancy).filter_by(status="pending").order_by(Vacancy.id).all()
        return templates.TemplateResponse(request, "admin_vacancies.html",
                                          {"vacancies": pending, "msg": msg})
    finally:
        db.close()


@router.post("/admin/vacancy/{vacancy_id}/approve")
def approve_vacancy(request: Request, vacancy_id: int):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        vacancy = db.get(Vacancy, vacancy_id)
        if not vacancy:
            raise HTTPException(status_code=404, detail="Vacancy not found")
        if vacancy.status != "pending":
            return RedirectResponse("/admin/vacancies", status_code=303)
        if not any(vs.is_required for vs in vacancy.skills):
            return RedirectResponse("/admin/vacancies?msg=no_required", status_code=303)
        if vacancy.deadline and vacancy.deadline < date.today():
            return RedirectResponse("/admin/vacancies?msg=past_deadline", status_code=303)
        vacancy.status = "published"
        if not vacancy.published_at:  # keep the date of the first publication
            vacancy.published_at = datetime.utcnow()
        vacancy.rejection_reason = None
        log_action(db, admin, "approve_vacancy", "vacancy", vacancy.id)
        db.commit()
        return RedirectResponse("/admin/vacancies?msg=approved", status_code=303)
    finally:
        db.close()


@router.post("/admin/vacancy/{vacancy_id}/reject")
def reject_vacancy(request: Request, vacancy_id: int, reason: str = Form("")):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        vacancy = db.get(Vacancy, vacancy_id)
        if not vacancy:
            raise HTTPException(status_code=404, detail="Vacancy not found")
        if vacancy.status != "pending":
            return RedirectResponse("/admin/vacancies", status_code=303)
        reason = reason.strip()
        if not reason:
            return RedirectResponse("/admin/vacancies?msg=reason_required", status_code=303)
        vacancy.status = "rejected"
        vacancy.rejection_reason = reason[:1000]
        log_action(db, admin, "reject_vacancy", "vacancy", vacancy.id, reason[:1000])
        db.commit()
        return RedirectResponse("/admin/vacancies?msg=rejected", status_code=303)
    finally:
        db.close()