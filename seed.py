from database import Base, engine, SessionLocal, Skill, Vacancy, VacancySkill

Base.metadata.create_all(engine)
db = SessionLocal()

if db.query(Vacancy).count() > 0:
    print("Demo data already exists")
    raise SystemExit


def get_skill(name):
    skill = db.query(Skill).filter_by(name=name).first()
    if not skill:
        skill = Skill(name=name)
        db.add(skill)
        db.flush()
    return skill


# title, company, direction, level, city, format, required skills, optional skills
DEMO = [
    ("Data Analyst Intern", "Demo Company A", "Data Analytics", "Internship", "Astana", "Hybrid",
     ["Python", "SQL", "Excel", "Power BI"], ["Tableau"]),
    ("Junior Data Analyst", "Demo Company B", "Data Analytics", "Junior", "Almaty", "Remote",
     ["SQL", "Excel", "Power BI"], ["Python"]),
    ("Data Science Intern", "Demo Company C", "Data Science", "Internship", "Astana", "On-site",
     ["Python", "Pandas", "Machine Learning"], ["SQL", "Git"]),
    ("Backend Developer Intern", "Demo Company D", "Software Development", "Internship", "Astana", "Hybrid",
     ["Python", "FastAPI", "SQL", "Git"], ["Docker"]),
    ("Junior Frontend Developer", "Demo Company E", "Software Development", "Junior", "Almaty", "Remote",
     ["JavaScript", "HTML", "CSS", "React"], ["TypeScript", "Git"]),
    ("QA Trainee", "Demo Company F", "QA", "Trainee", "Astana", "On-site",
     ["Manual Testing", "Test Cases"], ["SQL", "Postman"]),
    ("Junior Security Analyst", "Demo Company G", "Cybersecurity", "Junior", "Astana", "Hybrid",
     ["Networking", "Linux", "Security Basics"], ["Python"]),
    ("UI/UX Design Intern", "Demo Company H", "UI/UX", "Internship", "Remote", "Remote",
     ["Figma", "Wireframing"], ["User Research"]),
]

for title, company, direction, level, city, fmt, required, optional in DEMO:
    vacancy = Vacancy(
        title=title, company=company, direction=direction, level=level,
        city=city, work_format=fmt,
        employment_type="Internship" if level == "Internship" else "Full-time",
        paid=True, description=f"Demo vacancy: {title}.",
        is_demo=True, status="published",
    )
    db.add(vacancy)
    db.flush()
    for name in required:
        db.add(VacancySkill(vacancy_id=vacancy.id, skill_id=get_skill(name).id, is_required=True))
    for name in optional:
        db.add(VacancySkill(vacancy_id=vacancy.id, skill_id=get_skill(name).id, is_required=False))

db.commit()
print("Done: demo vacancies added")