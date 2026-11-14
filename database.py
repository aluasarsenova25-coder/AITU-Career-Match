from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey, Text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

engine = create_engine("sqlite:///career_match.db", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False)
Base = declarative_base()


class Skill(Base):
    __tablename__ = "skills"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    first_name = Column(String)
    last_name = Column(String)
    role = Column(String, default="student")  # student / employer / admin
    direction = Column(String)
    work_format = Column(String)
    city = Column(String)
    student_skills = relationship("StudentSkill")



class StudentSkill(Base):
    __tablename__ = "student_skills"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    skill_id = Column(Integer, ForeignKey("skills.id"))
    skill = relationship("Skill")


class Vacancy(Base):
    __tablename__ = "vacancies"
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    company = Column(String, nullable=False)
    direction = Column(String)
    level = Column(String)  # Internship / Trainee / Junior
    city = Column(String)
    work_format = Column(String)  # On-site / Remote / Hybrid
    employment_type = Column(String)
    paid = Column(Boolean, default=True)
    description = Column(Text)
    is_demo = Column(Boolean, default=False)
    status = Column(String, default="published")
    skills = relationship("VacancySkill", back_populates="vacancy")


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
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    vacancy_id = Column(Integer, ForeignKey("vacancies.id"))
    vacancy = relationship("Vacancy")


class Application(Base):
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    vacancy_id = Column(Integer, ForeignKey("vacancies.id"))
    status = Column(String, default="sent")
    message = Column(Text)
    vacancy = relationship("Vacancy")