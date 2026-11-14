import json
import os

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from starlette.middleware.sessions import SessionMiddleware

from admin import router as admin_router
from database import (Application, ApplicationStatusHistory, Direction,
                      SavedVacancy, SessionLocal, Skill, StudentSkill, User,
                      Vacancy, expire_old_vacancies)
from employer import router as employer_router
from recommender import get_recommendations
from security import check_password, hash_password

app = FastAPI()
app.add_middleware(SessionMiddleware,
                   secret_key=os.environ.get("SECRET_KEY", "dev-secret-change-me"))
templates = Jinja2Templates(directory="templates")

FORMATS = ["On-site", "Remote", "Hybrid"]
ACTIVE_STATUSES = ("sent", "under_review", "interview")


# ---------- helpers ----------
def current_student(request, db):
    """Returns the logged-in student or None. The role is checked on the server."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.get(User, user_id)
    if not user or user.role != "student" or user.is_blocked:
        return None
    return user


def redirect_for_role(request):
    role = request.session.get("role")
    if role == "employer":
        return RedirectResponse("/employer", status_code=303)
    if role == "admin":
        return RedirectResponse("/admin", status_code=303)
    return RedirectResponse("/login", status_code=303)


def safe_back(url: str) -> str:
    return url if url.startswith("/") and not url.startswith("//") else "/"


# ---------- catalog ----------
@app.get("/")
def home(request: Request, q: str = "", direction: str = ""):
    db = SessionLocal()
    try:
        query = db.query(Vacancy).filter(Vacancy.status == "published")
        if q:
            query = query.filter(or_(Vacancy.title.ilike(f"%{q}%"),
                                     Vacancy.company.ilike(f"%{q}%")))
        if direction:
            query = query.filter(Vacancy.direction == direction)
        vacancies = query.order_by(Vacancy.id.desc()).all()
        directions = [d[0] for d in db.query(Vacancy.direction).distinct() if d[0]]
        return templates.TemplateResponse(request, "index.html", {
            "vacancies": vacancies, "directions": directions,
            "q": q, "direction": direction})
    finally:
        db.close()


@app.get("/api/vacancies")
def api_vacancies():
    db = SessionLocal()
    try:
        return [
            {"id": v.id, "title": v.title, "company": v.company,
             "direction": v.direction, "skills": [s.skill.name for s in v.skills]}
            for v in db.query(Vacancy).filter(Vacancy.status == "published").all()
        ]
    finally:
        db.close()


# ---------- registration / login ----------
@app.get("/register")
def register_page(request: Request):
    return templates.TemplateResponse(request, "register.html", {"error": None})


@app.post("/register")
def register_submit(request: Request,
                    first_name: str = Form(...), last_name: str = Form(...),
                    email: str = Form(...), password: str = Form(...),
                    password2: str = Form(...), consent: str = Form(None)):
    email = email.strip().lower()
    error = None
    if "@" not in email:
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
            return templates.TemplateResponse(request, "register.html", {
                "error": error, "first_name": first_name,
                "last_name": last_name, "email": email})
        user = User(email=email, password_hash=hash_password(password),
                    first_name=first_name.strip(), last_name=last_name.strip(),
                    role="student")
        db.add(user)
        db.commit()
        request.session["user_id"] = user.id
        request.session["user_name"] = user.first_name
        request.session["role"] = "student"
        return RedirectResponse("/profile", status_code=303)
    finally:
        db.close()


@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
def login_submit(request: Request, email: str = Form(...), password: str = Form(...)):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(email=email.strip().lower()).first()
        if not user or not check_password(password, user.password_hash):
            return templates.TemplateResponse(request, "login.html", {
                "error": "Invalid email or password.", "email": email})
        if user.is_blocked:
            return templates.TemplateResponse(request, "login.html", {
                "error": "This account is blocked.", "email": email})
        request.session["user_id"] = user.id
        request.session["user_name"] = user.first_name
        request.session["role"] = user.role
        if user.role == "employer":
            return RedirectResponse("/employer", status_code=303)
        if user.role == "admin":
            return RedirectResponse("/admin", status_code=303)
        return RedirectResponse("/", status_code=303)
    finally:
        db.close()


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


# ---------- student profile ----------
def render_profile(request, db, user, saved=False):
    all_skills = db.query(Skill).order_by(Skill.name).all()
    my_skill_ids = {s.skill_id for s in
                    db.query(StudentSkill).filter_by(user_id=user.id)}
    directions = [d.name for d in db.query(Direction).order_by(Direction.id)]
    return templates.TemplateResponse(request, "profile.html", {
        "user": user, "all_skills": all_skills, "my_skill_ids": my_skill_ids,
        "directions": directions, "formats": FORMATS, "saved": saved})


@app.get("/profile")
def profile_page(request: Request):
    db = SessionLocal()
    try:
        user = current_student(request, db)
        if not user:
            return redirect_for_role(request)
        return render_profile(request, db, user)
    finally:
        db.close()


@app.post("/profile")
def profile_save(request: Request,
                 direction: str = Form(""), work_format: str = Form(""),
                 city: str = Form(""), skill_ids: list[int] = Form(default=[])):
    db = SessionLocal()
    try:
        user = current_student(request, db)
        if not user:
            return redirect_for_role(request)
        directions = [d.name for d in db.query(Direction)]
        user.direction = direction if direction in directions else ""
        user.work_format = work_format if work_format in FORMATS else ""
        user.city = city.strip()
        valid_ids = {row[0] for row in db.query(Skill.id)}
        db.query(StudentSkill).filter_by(user_id=user.id).delete()
        for sid in set(skill_ids) & valid_ids:
            db.add(StudentSkill(user_id=user.id, skill_id=sid))
        db.commit()
        return render_profile(request, db, user, saved=True)
    finally:
        db.close()


# ---------- recommendations ----------
@app.get("/recommendations")
def recommendations_page(request: Request):
    db = SessionLocal()
    try:
        user = current_student(request, db)
        if not user:
            return redirect_for_role(request)
        data = get_recommendations(db, user)
        return templates.TemplateResponse(request, "recommendations.html",
                                          {"user": user, **data})
    finally:
        db.close()


# ---------- vacancy page, favorites, applications ----------
@app.get("/vacancy/{vacancy_id}")
def vacancy_page(request: Request, vacancy_id: int, error: str = ""):
    db = SessionLocal()
    try:
        vacancy = db.get(Vacancy, vacancy_id)
        if not vacancy or vacancy.status != "published":
            raise HTTPException(status_code=404, detail="Vacancy not found")
        user = current_student(request, db)
        my_skills, saved, application = set(), False, None
        if user:
            my_skills = {ss.skill.name for ss in user.student_skills}
            saved = db.query(SavedVacancy).filter_by(
                user_id=user.id, vacancy_id=vacancy_id).first() is not None
            application = db.query(Application).filter(
                Application.user_id == user.id,
                Application.vacancy_id == vacancy_id,
                Application.status.in_(ACTIVE_STATUSES)).first()
        return templates.TemplateResponse(request, "vacancy.html", {
            "vacancy": vacancy, "user": user, "my_skills": my_skills,
            "saved": saved, "application": application, "error": error})
    finally:
        db.close()


@app.post("/vacancy/{vacancy_id}/save")
def toggle_save(request: Request, vacancy_id: int, back: str = Form("/favorites")):
    db = SessionLocal()
    try:
        user = current_student(request, db)
        if not user:
            return redirect_for_role(request)
        row = db.query(SavedVacancy).filter_by(
            user_id=user.id, vacancy_id=vacancy_id).first()
        if row:
            db.delete(row)
        elif db.get(Vacancy, vacancy_id):
            db.add(SavedVacancy(user_id=user.id, vacancy_id=vacancy_id))
        db.commit()
    finally:
        db.close()
    return RedirectResponse(safe_back(back), status_code=303)


@app.post("/vacancy/{vacancy_id}/apply")
def apply_to_vacancy(request: Request, vacancy_id: int,
                     message: str = Form(""), consent: str = Form(None)):
    db = SessionLocal()
    try:
        user = current_student(request, db)
        if not user:
            return redirect_for_role(request)
        if not consent:
            return RedirectResponse(f"/vacancy/{vacancy_id}?error=consent", status_code=303)
        vacancy = db.get(Vacancy, vacancy_id)
        if not vacancy or vacancy.status != "published":
            raise HTTPException(status_code=404, detail="Vacancy not found")
        existing = db.query(Application).filter(
            Application.user_id == user.id,
            Application.vacancy_id == vacancy_id,
            Application.status.in_(ACTIVE_STATUSES)).first()
        if not existing:  # a repeated click does not create a duplicate
            snapshot = json.dumps({
                "name": f"{user.first_name} {user.last_name}".strip(),
                "email": user.email, "direction": user.direction,
                "work_format": user.work_format, "city": user.city,
                "skills": sorted(ss.skill.name for ss in user.student_skills),
            }, ensure_ascii=False)
            application = Application(user_id=user.id, vacancy_id=vacancy_id,
                                      status="sent", message=message.strip()[:1000],
                                      snapshot=snapshot)
            db.add(application)
            db.flush()
            db.add(ApplicationStatusHistory(application_id=application.id, status="sent"))
            db.commit()
    finally:
        db.close()
    return RedirectResponse(f"/vacancy/{vacancy_id}", status_code=303)


@app.get("/favorites")
def favorites_page(request: Request):
    db = SessionLocal()
    try:
        user = current_student(request, db)
        if not user:
            return redirect_for_role(request)
        rows = db.query(SavedVacancy).filter_by(user_id=user.id).all()
        vacancies = [r.vacancy for r in rows
                     if r.vacancy and r.vacancy.status == "published"]
        return templates.TemplateResponse(request, "favorites.html",
                                          {"vacancies": vacancies})
    finally:
        db.close()


@app.get("/applications")
def applications_page(request: Request):
    db = SessionLocal()
    try:
        user = current_student(request, db)
        if not user:
            return redirect_for_role(request)
        rows = db.query(Application).filter_by(user_id=user.id) \
                 .order_by(Application.id.desc()).all()
        return templates.TemplateResponse(request, "applications.html", {
            "applications": rows, "active": ACTIVE_STATUSES})
    finally:
        db.close()


@app.post("/applications/{application_id}/withdraw")
def withdraw_application(request: Request, application_id: int):
    db = SessionLocal()
    try:
        user = current_student(request, db)
        if not user:
            return redirect_for_role(request)
        row = db.get(Application, application_id)
        if not row or row.user_id != user.id:
            raise HTTPException(status_code=404, detail="Application not found")
        if row.status in ACTIVE_STATUSES:
            row.status = "withdrawn"
            db.add(ApplicationStatusHistory(application_id=row.id, status="withdrawn"))
            db.commit()
    finally:
        db.close()
    return RedirectResponse("/applications", status_code=303)


# ---------- routers and housekeeping ----------
app.include_router(employer_router)
app.include_router(admin_router)


@app.middleware("http")
async def expire_middleware(request: Request, call_next):
    expire_old_vacancies()  # published vacancies past their deadline become "expired"
    return await call_next(request)