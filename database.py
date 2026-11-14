import os
from datetime import date, datetime

from sqlalchemy import (Boolean, Column, Date, DateTime, ForeignKey, Integer,
                        String, Text, UniqueConstraint, create_engine)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

# SQLite by default; set DATABASE_URL to use PostgreSQL later
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///career_match.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False)
Base = declarative_base()


class Direction(Base):
    __tablename__ = "directions"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)


class Skill(Base):
    __tablename__ = "skills"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    aliases = relationship("SkillAlias", back_populates="skill")


class SkillAlias(Base):
    __tablename__ = "skill_aliases"
    id = Column(Integer, primary_key=True)
    skill_id = Column(Integer, ForeignKey("skills.id"), nullable=False)
    alias = Column(String, unique=True, nullable=False)
    skill = relationship("Skill", back_populates="aliases")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    first_name = Column(String)
    last_name = Column(String)
    role = Column(String, default="student")  # student / employer / admin
    is_blocked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    # student profile
    specialty = Column(String)
    course = Column(Integer)
    graduation_year = Column(Integer)
    direction = Column(String)
    work_format = Column(String)
    employment_type = Column(String)
    city = Column(String)
    languages = Column(String)
    github_url = Column(String)
    portfolio_url = Column(String)
    resume_path = Column(String)

    student_skills = relationship("StudentSkill")
    projects = relationship("Project", back_populates="user")
    employer = relationship("EmployerProfile", back_populates="user", uselist=False)


class EmployerProfile(Base):
    __tablename__ = "employer_profiles"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    company_name = Column(String, nullable=False)
    contact_name = Column(String)
    website = Column(String)
    description = Column(Text)
    verified = Column(Boolean, default=False)
    user = relationship("User", back_populates="employer")
    vacancies = relationship("Vacancy", back_populates="employer")


class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String, nullable=False)
    description = Column(Text)
    link = Column(String)
    user = relationship("User", back_populates="projects")
    skills = relationship("ProjectSkill", cascade="all, delete-orphan")


class ProjectSkill(Base):
    __tablename__ = "project_skills"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    skill_id = Column(Integer, ForeignKey("skills.id"))
    skill = relationship("Skill")


class StudentSkill(Base):
    __tablename__ = "student_skills"
    __table_args__ = (UniqueConstraint("user_id", "skill_id"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    skill_id = Column(Integer, ForeignKey("skills.id"))
    skill = relationship("Skill")


class Vacancy(Base):
    __tablename__ = "vacancies"
    id = Column(Integer, primary_key=True)
    employer_id = Column(Integer, ForeignKey("employer_profiles.id"), nullable=True)
    title = Column(String, nullable=False)
    company = Column(String, nullable=False)
    direction = Column(String)
    level = Column(String)  # Internship / Trainee / Junior
    city = Column(String)
    work_format = Column(String)  # On-site / Remote / Hybrid
    employment_type = Column(String)
    paid = Column(Boolean, default=True)
    salary_min = Column(Integer)
    salary_max = Column(Integer)
    currency = Column(String)
    salary_period = Column(String)
    description = Column(Text)
    deadline = Column(Date)
    published_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    # draft / pending / published / rejected / closed / expired
    status = Column(String, default="draft")
    rejection_reason = Column(Text)
    is_demo = Column(Boolean, default=False)
    source = Column(String, default="employer")  # demo / employer / admin / csv
    external_id = Column(String, unique=True)

    skills = relationship("VacancySkill", back_populates="vacancy",
                          cascade="all, delete-orphan")
    employer = relationship("EmployerProfile", back_populates="vacancies")


class VacancySkill(Base):
    __tablename__ = "vacancy_skills"
    id = Column(Integer, primary_key=True)
    vacancy_id = Column(Integer, ForeignKey("vacancies.id"))
    skill_id = Column(Integer, ForeignKey("skills.id"))
    is_required = Column(Boolean, default=True)
    vacancy = relationship("Vacancy", back_populates="skills")
    skill = relationship("Skill")


class SavedVacancy(Base):
    __tablename__ = "saved_vacancies"
    __table_args__ = (UniqueConstraint("user_id", "vacancy_id"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    vacancy_id = Column(Integer, ForeignKey("vacancies.id"))
    vacancy = relationship("Vacancy")


class Application(Base):
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    vacancy_id = Column(Integer, ForeignKey("vacancies.id"))
    # sent / under_review / interview / rejected / withdrawn
    status = Column(String, default="sent")
    message = Column(Text)
    snapshot = Column(Text)  # data transferred at the moment of applying
    created_at = Column(DateTime, default=datetime.utcnow)
    vacancy = relationship("Vacancy")


class ApplicationStatusHistory(Base):
    __tablename__ = "application_status_history"
    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"))
    status = Column(String)
    changed_at = Column(DateTime, default=datetime.utcnow)


class ModerationLog(Base):
    __tablename__ = "moderation_log"
    id = Column(Integer, primary_key=True)
    admin_id = Column(Integer, ForeignKey("users.id"))
    action = Column(String)
    target_type = Column(String)
    target_id = Column(Integer)
    reason = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


def expire_old_vacancies():
    """Published vacancies with a past deadline become 'expired'."""
    db = SessionLocal()
    try:
        db.query(Vacancy).filter(
            Vacancy.status == "published",
            Vacancy.deadline.isnot(None),
            Vacancy.deadline < date.today(),
        ).update({"status": "expired"}, synchronize_session=False)
        db.commit()
    finally:
        db.close()


Base.metadata.create_all(engine)