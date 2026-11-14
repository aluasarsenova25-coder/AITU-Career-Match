from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def home():
    return {"message": "AITU Career Match works!"}

from database import SessionLocal, Vacancy


@app.get("/vacancies")
def vacancies():
    db = SessionLocal()
    result = [
        {"id": v.id, "title": v.title, "company": v.company,
         "direction": v.direction, "skills": [s.skill.name for s in v.skills]}
        for v in db.query(Vacancy).all()
    ]
    db.close()
    return result