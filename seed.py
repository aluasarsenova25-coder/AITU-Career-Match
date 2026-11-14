from datetime import date, datetime, timedelta

from database import (Base, engine, SessionLocal, Skill, Vacancy,
                      VacancySkill, Direction)

Base.metadata.create_all(engine)
db = SessionLocal()

DIRECTIONS = ["Data Analytics", "Data Science", "Software Development", "QA",
              "Cybersecurity", "UI/UX", "IT Project Management"]
for name in DIRECTIONS:
    if not db.query(Direction).filter_by(name=name).first():
        db.add(Direction(name=name))
db.commit()

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


# title, company, direction, level, city, format, pay, required, optional
# pay: (min, max) in KZT per month, None = not disclosed, "unpaid" = unpaid
DEMO = [
    ("Data Analyst Intern", "Demo Company A", "Data Analytics", "Internship", "Astana", "Hybrid", (150000, 200000), ["Python", "SQL", "Excel", "Power BI"], ["Tableau"]),
    ("Junior Data Analyst", "Demo Company B", "Data Analytics", "Junior", "Almaty", "Remote", (300000, 400000), ["SQL", "Excel", "Power BI"], ["Python"]),
    ("BI Analyst Trainee", "Demo Company I", "Data Analytics", "Trainee", "Astana", "On-site", (200000, 260000), ["SQL", "Power BI"], ["Excel", "Tableau"]),
    ("Data Analytics Intern", "Demo Company J", "Data Analytics", "Internship", "Almaty", "Hybrid", None, ["Excel", "SQL"], ["Python"]),
    ("Data Science Intern", "Demo Company C", "Data Science", "Internship", "Astana", "On-site", (180000, 220000), ["Python", "Pandas", "Machine Learning"], ["SQL", "Git"]),
    ("Junior ML Engineer", "Demo Company K", "Data Science", "Junior", "Astana", "Remote", (450000, 600000), ["Python", "Machine Learning", "Pandas"], ["Docker", "Git"]),
    ("Backend Developer Intern", "Demo Company D", "Software Development", "Internship", "Astana", "Hybrid", (160000, 220000), ["Python", "FastAPI", "SQL", "Git"], ["Docker"]),
    ("Junior Frontend Developer", "Demo Company E", "Software Development", "Junior", "Almaty", "Remote", (350000, 450000), ["JavaScript", "HTML", "CSS", "React"], ["TypeScript", "Git"]),
    ("Junior Python Developer", "Demo Company L", "Software Development", "Junior", "Astana", "On-site", (320000, 420000), ["Python", "SQL", "Git"], ["FastAPI", "Docker"]),
    ("Frontend Intern", "Demo Company M", "Software Development", "Internship", "Astana", "Hybrid", "unpaid", ["HTML", "CSS", "JavaScript"], ["React"]),
    ("QA Trainee", "Demo Company F", "QA", "Trainee", "Astana", "On-site", (170000, 210000), ["Manual Testing", "Test Cases"], ["SQL", "Postman"]),
    ("Junior QA Engineer", "Demo Company N", "QA", "Junior", "Almaty", "Hybrid", (280000, 340000), ["Manual Testing", "Test Cases", "Postman"], ["SQL", "Git"]),
    ("Junior Security Analyst", "Demo Company G", "Cybersecurity", "Junior", "Astana", "Hybrid", (330000, 430000), ["Networking", "Linux", "Security Basics"], ["Python"]),
    ("Security Intern", "Demo Company O", "Cybersecurity", "Internship", "Astana", "On-site", None, ["Networking", "Security Basics"], ["Linux"]),
    ("UI/UX Design Intern", "Demo Company H", "UI/UX", "Internship", "Remote", "Remote", (140000, 180000), ["Figma", "Wireframing"], ["User Research"]),
    ("Junior UI/UX Designer", "Demo Company P", "UI/UX", "Junior", "Almaty", "Hybrid", (300000, 380000), ["Figma", "Wireframing", "User Research"], []),
    ("Project Management Intern", "Demo Company Q", "IT Project Management", "Internship", "Astana", "Hybrid", (140000, 170000), ["Jira", "Communication"], ["Scrum"]),
    ("Junior Project Coordinator", "Demo Company R", "IT Project Management", "Junior", "Astana", "On-site", (300000, 360000), ["Jira", "Scrum", "Communication"], ["Agile"]),
]

for i, (title, company, direction, level, city, fmt, pay, required, optional) in enumerate(DEMO):
    paid = pay != "unpaid"
    smin, smax = pay if isinstance(pay, tuple) else (None, None)
    vacancy = Vacancy(
        title=title, company=company, direction=direction, level=level,
        city=city, work_format=fmt,
        employment_type="Internship" if level == "Internship" else "Full-time",
        paid=paid, salary_min=smin, salary_max=smax,
        currency="KZT" if smin else None,
        salary_period="month" if smin else None,
        description=f"Demo vacancy: {title}. Work on real tasks together with a mentor in the {direction} team.",
        is_demo=True, source="demo", status="published",
        published_at=datetime.utcnow() - timedelta(days=i * 2),
        deadline=date.today() + timedelta(days=30 + i),
    )
    db.add(vacancy)
    for name in required:
        vacancy.skills.append(VacancySkill(skill=get_skill(name), is_required=True))
    for name in optional:
        vacancy.skills.append(VacancySkill(skill=get_skill(name), is_required=False))

db.commit()
print("Done: demo vacancies added")