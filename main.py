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