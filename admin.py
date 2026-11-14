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


def target_label(db, target_type, target_id):
    """Human-readable name of the object an action was applied to."""
    if target_type == "vacancy":
        item = db.get(Vacancy, target_id)
        return item.title if item else f"vacancy #{target_id}"
    if target_type == "company":
        item = db.get(EmployerProfile, target_id)
        return item.company_name if item else f"company #{target_id}"
    if target_type == "user":
        item = db.get(User, target_id)
        return item.email if item else f"user #{target_id}"
    return f"{target_type} #{target_id}"


@router.get("/admin/users")
def admin_users(request: Request, msg: str = ""):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        users = db.query(User).filter(User.role != "admin").order_by(User.id.desc()).all()
        return templates.TemplateResponse(request, "admin_users.html",
                                          {"users": users, "msg": msg})
    finally:
        db.close()


def set_user_blocked(request, user_id, value, reason=""):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        user = db.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if user.role == "admin":  # administrators cannot be blocked here
            return RedirectResponse("/admin/users", status_code=303)
        if user.is_blocked != value:
            user.is_blocked = value
            log_action(db, admin, "block_user" if value else "unblock_user",
                       "user", user.id, reason.strip()[:1000] or None)
            db.commit()
        return RedirectResponse("/admin/users?msg=" + ("blocked" if value else "unblocked"),
                                status_code=303)
    finally:
        db.close()


@router.post("/admin/user/{user_id}/block")
def block_user(request: Request, user_id: int, reason: str = Form("")):
    return set_user_blocked(request, user_id, True, reason)


@router.post("/admin/user/{user_id}/unblock")
def unblock_user(request: Request, user_id: int):
    return set_user_blocked(request, user_id, False)


@router.get("/admin/log")
def admin_log(request: Request):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        entries = db.query(ModerationLog).order_by(ModerationLog.id.desc()).limit(200).all()
        rows = []
        for e in entries:
            actor = db.get(User, e.admin_id)
            rows.append({
                "entry": e,
                "admin": actor.email if actor else "—",
                "target": target_label(db, e.target_type, e.target_id),
            })
        return templates.TemplateResponse(request, "admin_log.html", {"rows": rows})
    finally:
        db.close()