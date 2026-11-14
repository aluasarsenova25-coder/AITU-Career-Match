from datetime import date, datetime

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from database import (Application, ApplicationStatusHistory, Direction,
                      EmployerProfile, SessionLocal, Skill, User, Vacancy,
                      VacancySkill)
from security import hash_password

router = APIRouter()
templates = Jinja2Templates(directory="templates")

LEVELS = ["Internship", "Trainee", "Junior"]
FORMATS = ["On-site", "Remote", "Hybrid"]
EMPLOYMENT_TYPES = ["Internship", "Part-time", "Full-time"]
CURRENCIES = ["KZT", "USD", "EUR"]
PERIODS = ["month", "hour", "year"]
EMPLOYER_STATUSES = ["under_review", "interview", "rejected"]
FIELDS = ["title", "direction", "level", "city", "work_format", "employment_type",
          "salary_min", "salary_max", "currency", "salary_period", "deadline",
          "description"]


# ---------- helpers ----------
def get_employer_user(request, db):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.get(User, user_id)
    if not user or user.role != "employer" or user.is_blocked or not user.employer:
        return None
    return user


def owned_vacancy(db, employer, vacancy_id):
    vacancy = db.get(Vacancy, vacancy_id)
    if not vacancy or vacancy.employer_id != employer.id:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    return vacancy


def parse_int(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        number = int(value)
    except ValueError:
        return None
    return number if number >= 0 else None


def parse_date(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def direction_names(db):
    return [d.name for d in db.query(Direction).order_by(Direction.id)]


def form_context(db, **extra):
    ctx = {
        "directions": direction_names(db), "levels": LEVELS, "formats": FORMATS,
        "employment_types": EMPLOYMENT_TYPES, "currencies": CURRENCIES,
        "periods": PERIODS, "skills": db.query(Skill).order_by(Skill.name).all(),
    }
    ctx.update(extra)
    return ctx


def default_data():
    return {"paid": True, "currency": "KZT", "salary_period": "month",
            "req_ids": set(), "opt_ids": set()}


def data_from_form(form):
    data = {k: (form.get(k) or "") for k in FIELDS}
    data["paid"] = form.get("paid") == "1"
    data["req_ids"] = {int(x) for x in form.getlist("required_ids") if x.isdigit()}
    data["opt_ids"] = {int(x) for x in form.getlist("optional_ids") if x.isdigit()}
    return data


def data_from_vacancy(v):
    return {
        "title": v.title or "", "direction": v.direction or "", "level": v.level or "",
        "city": v.city or "", "work_format": v.work_format or "",
        "employment_type": v.employment_type or "",
        "salary_min": v.salary_min if v.salary_min is not None else "",
        "salary_max": v.salary_max if v.salary_max is not None else "",
        "currency": v.currency or "KZT", "salary_period": v.salary_period or "month",
        "deadline": v.deadline.isoformat() if v.deadline else "",
        "description": v.description or "", "paid": bool(v.paid),
        "req_ids": {vs.skill_id for vs in v.skills if vs.is_required},
        "opt_ids": {vs.skill_id for vs in v.skills if not vs.is_required},
    }


def validate_and_apply(db, vacancy, data):
    """Returns an error message or None. Fills the vacancy on success."""
    directions = direction_names(db)
    title = data["title"].strip()
    description = data["description"].strip()
    city = data["city"].strip()
    if not title or not description:
        return "Title and description are required."
    if data["direction"] not in directions:
        return "Please choose a career direction."
    if data["level"] not in LEVELS:
        return "Please choose a position level."
    if data["work_format"] not in FORMATS:
        return "Please choose a work format."
    if data["employment_type"] not in EMPLOYMENT_TYPES:
        return "Please choose an employment type."
    if not city and data["work_format"] != "Remote":
        return "Please enter a city (or choose the Remote format)."

    deadline = parse_date(data["deadline"])
    if data["deadline"].strip() and deadline is None:
        return "The deadline date is invalid."
    if deadline and deadline < date.today():
        return "The deadline cannot be in the past."

    salary_min = salary_max = None
    if data["paid"]:
        salary_min = parse_int(data["salary_min"])
        salary_max = parse_int(data["salary_max"])
        if (data["salary_min"].strip() and salary_min is None) or \
           (data["salary_max"].strip() and salary_max is None):
            return "Salary must be a positive whole number."
        if salary_min is not None and salary_max is not None and salary_min > salary_max:
            return "Minimum salary cannot be greater than the maximum."
    has_salary = salary_min is not None or salary_max is not None

    valid_ids = {row[0] for row in db.query(Skill.id)}
    req_ids = data["req_ids"] & valid_ids
    opt_ids = (data["opt_ids"] & valid_ids) - req_ids

    vacancy.title = title
    vacancy.description = description
    vacancy.direction = data["direction"]
    vacancy.level = data["level"]
    vacancy.work_format = data["work_format"]
    vacancy.employment_type = data["employment_type"]
    vacancy.city = city
    vacancy.deadline = deadline
    vacancy.paid = data["paid"]
    vacancy.salary_min = salary_min
    vacancy.salary_max = salary_max
    vacancy.currency = (data["currency"] if data["currency"] in CURRENCIES else "KZT") if has_salary else None
    vacancy.salary_period = (data["salary_period"] if data["salary_period"] in PERIODS else "month") if has_salary else None

    vacancy.skills.clear()
    for skill_id in req_ids:
        vacancy.skills.append(VacancySkill(skill_id=skill_id, is_required=True))
    for skill_id in opt_ids:
        vacancy.skills.append(VacancySkill(skill_id=skill_id, is_required=False))
    return None


# ---------- employer registration ----------
@router.get("/register/employer")
def register_employer_page(request: Request):
    return templates.TemplateResponse(request, "register_employer.html", {"error": None})


@router.post("/register/employer")
def register_employer_submit(request: Request,
                             company_name: str = Form(...), first_name: str = Form(...),
                             last_name: str = Form(...), email: str = Form(...),
                             password: str = Form(...), password2: str = Form(...),
                             consent: str = Form(None)):
    email = email.strip().lower()
    error = None
    if not company_name.strip():
        error = "Company name is required."
    elif "@" not in email:
        error = "Please enter a valid email."
    elif len(password) < 8:
        error = "Password must be at least 8 characters."
    elif password != password2:
        error = "Passwords do not match."
    elif not consent:
        error = "You must agree to the data processing rules."

    db = SessionLocal()
    try:
        if not error and db.query(User).filter_by(email=email).first():
            error = "An account with this email already exists."
        if error:
            return templates.TemplateResponse(request, "register_employer.html", {
                "error": error, "company_name": company_name, "first_name": first_name,
                "last_name": last_name, "email": email})
        user = User(email=email, password_hash=hash_password(password),
                    first_name=first_name.strip(), last_name=last_name.strip(),
                    role="employer")
        db.add(user)
        db.flush()
        db.add(EmployerProfile(user_id=user.id, company_name=company_name.strip(),
                               contact_name=f"{first_name.strip()} {last_name.strip()}"))
        db.commit()
        request.session["user_id"] = user.id
        request.session["user_name"] = user.first_name
        request.session["role"] = "employer"
        return RedirectResponse("/employer", status_code=303)
    finally:
        db.close()


# ---------- dashboard and company ----------
@router.get("/employer")
def employer_dashboard(request: Request, msg: str = ""):
    db = SessionLocal()
    try:
        user = get_employer_user(request, db)
        if not user:
            return RedirectResponse("/login", status_code=303)
        employer = user.employer
        vacancies = db.query(Vacancy).filter_by(employer_id=employer.id) \
                      .order_by(Vacancy.id.desc()).all()
        counts = {v.id: db.query(Application).filter_by(vacancy_id=v.id).count()
                  for v in vacancies}
        return templates.TemplateResponse(request, "employer_dashboard.html", {
            "employer": employer, "vacancies": vacancies, "counts": counts, "msg": msg})
    finally:
        db.close()


@router.get("/employer/company")
def company_page(request: Request):
    db = SessionLocal()
    try:
        user = get_employer_user(request, db)
        if not user:
            return RedirectResponse("/login", status_code=303)
        return templates.TemplateResponse(request, "employer_company.html", {
            "employer": user.employer, "error": None})
    finally:
        db.close()


@router.post("/employer/company")
def company_save(request: Request, company_name: str = Form(...),
                 contact_name: str = Form(""), website: str = Form(""),
                 description: str = Form("")):
    db = SessionLocal()
    try:
        user = get_employer_user(request, db)
        if not user:
            return RedirectResponse("/login", status_code=303)
        employer = user.employer
        website = website.strip()
        error = None
        if not company_name.strip():
            error = "Company name is required."
        elif website and not website.startswith(("http://", "https://")):
            error = "Website must start with http:// or https://"
        if error:
            return templates.TemplateResponse(request, "employer_company.html", {
                "employer": employer, "error": error})
        employer.company_name = company_name.strip()
        employer.contact_name = contact_name.strip()
        employer.website = website
        employer.description = description.strip()
        db.commit()
        return RedirectResponse("/employer?msg=company_saved", status_code=303)
    finally:
        db.close()


# ---------- vacancies ----------
@router.get("/employer/vacancy/new")
def vacancy_new_page(request: Request):
    db = SessionLocal()
    try:
        user = get_employer_user(request, db)
        if not user:
            return RedirectResponse("/login", status_code=303)
        return templates.TemplateResponse(request, "employer_vacancy_form.html", form_context(
            db, heading="New vacancy", action="/employer/vacancy/new",
            data=default_data(), error=None))
    finally:
        db.close()


@router.post("/employer/vacancy/new")
async def vacancy_new_submit(request: Request):
    form = await request.form()
    data = data_from_form(form)
    db = SessionLocal()
    try:
        user = get_employer_user(request, db)
        if not user:
            return RedirectResponse("/login", status_code=303)
        employer = user.employer
        vacancy = Vacancy(employer_id=employer.id, company=employer.company_name,
                          status="draft", source="employer", is_demo=False)
        error = validate_and_apply(db, vacancy, data)
        if error:
            return templates.TemplateResponse(request, "employer_vacancy_form.html", form_context(
                db, heading="New vacancy", action="/employer/vacancy/new",
                data=data, error=error))
        db.add(vacancy)
        db.commit()
        return RedirectResponse("/employer?msg=saved", status_code=303)
    finally:
        db.close()


@router.get("/employer/vacancy/{vacancy_id}/edit")
def vacancy_edit_page(request: Request, vacancy_id: int):
    db = SessionLocal()
    try:
        user = get_employer_user(request, db)
        if not user:
            return RedirectResponse("/login", status_code=303)
        vacancy = owned_vacancy(db, user.employer, vacancy_id)
        if vacancy.status == "closed":
            return RedirectResponse("/employer?msg=locked", status_code=303)
        return templates.TemplateResponse(request, "employer_vacancy_form.html", form_context(
            db, heading="Edit vacancy", action=f"/employer/vacancy/{vacancy.id}/edit",
            data=data_from_vacancy(vacancy), error=None, vacancy=vacancy))
    finally:
        db.close()


@router.post("/employer/vacancy/{vacancy_id}/edit")
async def vacancy_edit_submit(request: Request, vacancy_id: int):
    form = await request.form()
    data = data_from_form(form)
    db = SessionLocal()
    try:
        user = get_employer_user(request, db)
        if not user:
            return RedirectResponse("/login", status_code=303)
        vacancy = owned_vacancy(db, user.employer, vacancy_id)
        if vacancy.status == "closed":
            return RedirectResponse("/employer?msg=locked", status_code=303)
        error = validate_and_apply(db, vacancy, data)
        if error:
            db.rollback()
            return templates.TemplateResponse(request, "employer_vacancy_form.html", form_context(
                db, heading="Edit vacancy", action=f"/employer/vacancy/{vacancy.id}/edit",
                data=data, error=error, vacancy=vacancy))
        if vacancy.status == "published":
            vacancy.status = "pending"  # a changed published vacancy is re-moderated
        elif vacancy.status in ("rejected", "expired"):
            vacancy.status = "draft"
        db.commit()
        return RedirectResponse("/employer?msg=saved", status_code=303)
    finally:
        db.close()


@router.post("/employer/vacancy/{vacancy_id}/submit")
def vacancy_submit(request: Request, vacancy_id: int):
    db = SessionLocal()
    try:
        user = get_employer_user(request, db)
        if not user:
            return RedirectResponse("/login", status_code=303)
        employer = user.employer
        vacancy = owned_vacancy(db, employer, vacancy_id)
        if vacancy.status not in ("draft", "rejected"):
            return RedirectResponse("/employer", status_code=303)
        if not employer.verified:
            return RedirectResponse("/employer?msg=not_verified", status_code=303)
        if not any(vs.is_required for vs in vacancy.skills):
            return RedirectResponse("/employer?msg=no_required", status_code=303)
        vacancy.status = "pending"
        vacancy.rejection_reason = None
        db.commit()
        return RedirectResponse("/employer?msg=submitted", status_code=303)
    finally:
        db.close()


@router.post("/employer/vacancy/{vacancy_id}/close")
def vacancy_close(request: Request, vacancy_id: int):
    db = SessionLocal()
    try:
        user = get_employer_user(request, db)
        if not user:
            return RedirectResponse("/login", status_code=303)
        vacancy = owned_vacancy(db, user.employer, vacancy_id)
        if vacancy.status != "closed":
            vacancy.status = "closed"
            db.commit()
        return RedirectResponse("/employer?msg=closed", status_code=303)
    finally:
        db.close()


# ---------- applications ----------
@router.get("/employer/vacancy/{vacancy_id}/applications")
def vacancy_applications(request: Request, vacancy_id: int):
    db = SessionLocal()
    try:
        user = get_employer_user(request, db)
        if not user:
            return RedirectResponse("/login", status_code=303)
        vacancy = owned_vacancy(db, user.employer, vacancy_id)
        apps = db.query(Application).filter_by(vacancy_id=vacancy.id) \
                 .order_by(Application.id.desc()).all()
        rows = []
        for a in apps:
            student = db.get(User, a.user_id)
            rows.append({
                "application": a, "student": student,
                "skills": sorted(ss.skill.name for ss in student.student_skills),
            })
        return templates.TemplateResponse(request, "employer_applications.html", {
            "vacancy": vacancy, "rows": rows, "statuses": EMPLOYER_STATUSES})
    finally:
        db.close()


@router.post("/employer/application/{application_id}/status")
def change_application_status(request: Request, application_id: int,
                              status: str = Form(...)):
    db = SessionLocal()
    try:
        user = get_employer_user(request, db)
        if not user:
            return RedirectResponse("/login", status_code=303)
        application = db.get(Application, application_id)
        vacancy = db.get(Vacancy, application.vacancy_id) if application else None
        if not application or not vacancy or vacancy.employer_id != user.employer.id:
            raise HTTPException(status_code=404, detail="Application not found")
        if (status in EMPLOYER_STATUSES and application.status != "withdrawn"
                and application.status != status):
            application.status = status
            db.add(ApplicationStatusHistory(application_id=application.id, status=status))
            db.commit()
        return RedirectResponse(f"/employer/vacancy/{vacancy.id}/applications", status_code=303)
    finally:
        db.close()