import hashlib
import hmac
import os

from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from starlette.middleware.sessions import SessionMiddleware

from database import SessionLocal, Vacancy, User, Skill, StudentSkill

app = FastAPI()
app.add_middleware(SessionMiddleware,
                   secret_key=os.environ.get("SECRET_KEY", "dev-secret-change-me"))
templates = Jinja2Templates(directory="templates")

DIRECTIONS = ["Data Analytics", "Data Science", "Software Development",
              "QA", "Cybersecurity", "UI/UX", "IT Project Management"]
FORMATS = ["On-site", "Remote", "Hybrid"]


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return salt.hex() + "$" + digest.hex()


def check_password(password: str, stored: str) -> bool:
    salt_hex, digest_hex = stored.split("$")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 200_000)
    return hmac.compare_digest(digest.hex(), digest_hex)


# ---------- Catalog ----------
@app.get("/")
def home(request: Request, q: str = "", direction: str = ""):
    db = SessionLocal()
    query = db.query(Vacancy).filter(Vacancy.status == "published")
    if q:
        query = query.filter(or_(Vacancy.title.ilike(f"%{q}%"),
                                 Vacancy.company.ilike(f"%{q}%")))
    if direction:
        query = query.filter(Vacancy.direction == direction)
    vacancies = query.all()
    directions = [d[0] for d in db.query(Vacancy.direction).distinct() if d[0]]
    response = templates.TemplateResponse(request, "index.html", {
        "vacancies": vacancies,
        "directions": directions,
        "q": q,
        "direction": direction,
    })
    db.close()
    return response


@app.get("/api/vacancies")
def api_vacancies():
    db = SessionLocal()
    result = [
        {"id": v.id, "title": v.title, "company": v.company,
         "direction": v.direction, "skills": [s.skill.name for s in v.skills]}
        for v in db.query(Vacancy).all()
    ]
    db.close()
    return result


# ---------- Registration / login ----------
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
        request.session["user_id"] = user.id
        request.session["user_name"] = user.first_name
        return RedirectResponse("/", status_code=303)
    finally:
        db.close()


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


# ---------- Student profile ----------
def render_profile(request, db, user, saved=False):
    all_skills = db.query(Skill).order_by(Skill.name).all()
    my_skill_ids = {s.skill_id for s in
                    db.query(StudentSkill).filter_by(user_id=user.id)}
    return templates.TemplateResponse(request, "profile.html", {
        "user": user, "all_skills": all_skills, "my_skill_ids": my_skill_ids,
        "directions": DIRECTIONS, "formats": FORMATS, "saved": saved})


@app.get("/profile")
def profile_page(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        return render_profile(request, db, user)
    finally:
        db.close()


@app.post("/profile")
def profile_save(request: Request,
                 direction: str = Form(""), work_format: str = Form(""),
                 city: str = Form(""), skill_ids: list[int] = Form(default=[])):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        user.direction = direction
        user.work_format = work_format
        user.city = city.strip()
        db.query(StudentSkill).filter_by(user_id=user.id).delete()
        for sid in set(skill_ids):
            db.add(StudentSkill(user_id=user.id, skill_id=sid))
        db.commit()
        return render_profile(request, db, user, saved=True)
    finally:
        db.close()

from recommender import get_recommendations


@app.get("/recommendations")
def recommendations_page(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        data = get_recommendations(db, user)
        return templates.TemplateResponse(request, "recommendations.html",
                                          {"user": user, **data})
    finally:
        db.close()

from fastapi import HTTPException
from database import SavedVacancy, Application

ACTIVE_STATUSES = ("sent", "under_review", "interview")


def safe_back(url: str) -> str:
    return url if url.startswith("/") and not url.startswith("//") else "/"


@app.get("/vacancy/{vacancy_id}")
def vacancy_page(request: Request, vacancy_id: int, error: str = ""):
    db = SessionLocal()
    try:
        vacancy = db.get(Vacancy, vacancy_id)
        if not vacancy or vacancy.status != "published":
            raise HTTPException(status_code=404, detail="Vacancy not found")
        user, my_skills, saved, application = None, set(), False, None
        user_id = request.session.get("user_id")
        if user_id:
            user = db.get(User, user_id)
            my_skills = {ss.skill.name for ss in user.student_skills}
            saved = db.query(SavedVacancy).filter_by(
                user_id=user_id, vacancy_id=vacancy_id).first() is not None
            application = db.query(Application).filter(
                Application.user_id == user_id,
                Application.vacancy_id == vacancy_id,
                Application.status.in_(ACTIVE_STATUSES)).first()
        return templates.TemplateResponse(request, "vacancy.html", {
            "vacancy": vacancy, "user": user, "my_skills": my_skills,
            "saved": saved, "application": application, "error": error})
    finally:
        db.close()


@app.post("/vacancy/{vacancy_id}/save")
def toggle_save(request: Request, vacancy_id: int, back: str = Form("/favorites")):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    db = SessionLocal()
    try:
        row = db.query(SavedVacancy).filter_by(
            user_id=user_id, vacancy_id=vacancy_id).first()
        if row:
            db.delete(row)
        elif db.get(Vacancy, vacancy_id):
            db.add(SavedVacancy(user_id=user_id, vacancy_id=vacancy_id))
        db.commit()
    finally:
        db.close()
    return RedirectResponse(safe_back(back), status_code=303)


@app.post("/vacancy/{vacancy_id}/apply")
def apply_to_vacancy(request: Request, vacancy_id: int,
                     message: str = Form(""), consent: str = Form(None)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    if not consent:
        return RedirectResponse(f"/vacancy/{vacancy_id}?error=consent", status_code=303)
    db = SessionLocal()
    try:
        vacancy = db.get(Vacancy, vacancy_id)
        if not vacancy or vacancy.status != "published":
            raise HTTPException(status_code=404, detail="Vacancy not found")
        existing = db.query(Application).filter(
            Application.user_id == user_id,
            Application.vacancy_id == vacancy_id,
            Application.status.in_(ACTIVE_STATUSES)).first()
        if not existing:  # a repeated click does not create a duplicate
            db.add(Application(user_id=user_id, vacancy_id=vacancy_id,
                               status="sent", message=message.strip()[:1000]))
            db.commit()
    finally:
        db.close()
    return RedirectResponse(f"/vacancy/{vacancy_id}", status_code=303)


@app.get("/favorites")
def favorites_page(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    db = SessionLocal()
    try:
        rows = db.query(SavedVacancy).filter_by(user_id=user_id).all()
        vacancies = [r.vacancy for r in rows
                     if r.vacancy and r.vacancy.status == "published"]
        return templates.TemplateResponse(request, "favorites.html",
                                          {"vacancies": vacancies})
    finally:
        db.close()


@app.get("/applications")
def applications_page(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    db = SessionLocal()
    try:
        rows = db.query(Application).filter_by(user_id=user_id) \
                 .order_by(Application.id.desc()).all()
        return templates.TemplateResponse(request, "applications.html", {
            "applications": rows, "active": ACTIVE_STATUSES})
    finally:
        db.close()


@app.post("/applications/{application_id}/withdraw")
def withdraw_application(request: Request, application_id: int):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    db = SessionLocal()
    try:
        row = db.get(Application, application_id)
        if not row or row.user_id != user_id:
            raise HTTPException(status_code=404, detail="Application not found")
        if row.status in ACTIVE_STATUSES:
            row.status = "withdrawn"
            db.commit()
    finally:
        db.close()
    return RedirectResponse("/applications", status_code=303)