from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from database import SessionLocal, Vacancy

app = FastAPI()
templates = Jinja2Templates(directory="templates")


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