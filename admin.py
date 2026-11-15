from datetime import date, datetime

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from fastapi.templating import Jinja2Templates

from database import EmployerProfile, ModerationLog, SessionLocal, User, Vacancy
from database import Direction

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def get_admin(request, db):
    """Returns the admin user or None. The role is always checked on the server."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.get(User, user_id)
    if not user or user.role != "admin" or user.is_blocked:
        return None
    return user


def log_action(db, admin, action, target_type, target_id, reason=None):
    db.add(ModerationLog(admin_id=admin.id, action=action, target_type=target_type,
                         target_id=target_id, reason=reason))


@router.get("/admin")
def admin_companies(request: Request):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        companies = db.query(EmployerProfile).order_by(
            EmployerProfile.verified, EmployerProfile.id.desc()).all()
        rows = [{
            "company": c,
            "email": c.user.email if c.user else "",
            "vacancy_count": db.query(Vacancy).filter_by(employer_id=c.id).count(),
        } for c in companies]
        return templates.TemplateResponse(request, "admin_companies.html", {"rows": rows})
    finally:
        db.close()


def set_verified(request, company_id, value):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        company = db.get(EmployerProfile, company_id)
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        if company.verified != value:
            company.verified = value
            log_action(db, admin, "verify_company" if value else "unverify_company",
                       "company", company.id)
            db.commit()
        return RedirectResponse("/admin", status_code=303)
    finally:
        db.close()


@router.post("/admin/company/{company_id}/verify")
def verify_company(request: Request, company_id: int):
    return set_verified(request, company_id, True)


@router.post("/admin/company/{company_id}/unverify")
def unverify_company(request: Request, company_id: int):
    return set_verified(request, company_id, False)

@router.get("/admin/vacancies")
def admin_vacancies(request: Request, msg: str = ""):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        pending = db.query(Vacancy).filter_by(status="pending").order_by(Vacancy.id).all()
        return templates.TemplateResponse(request, "admin_vacancies.html",
                                          {"vacancies": pending, "msg": msg})
    finally:
        db.close()


@router.post("/admin/vacancy/{vacancy_id}/approve")
def approve_vacancy(request: Request, vacancy_id: int):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        vacancy = db.get(Vacancy, vacancy_id)
        if not vacancy:
            raise HTTPException(status_code=404, detail="Vacancy not found")
        if vacancy.status != "pending":
            return RedirectResponse("/admin/vacancies", status_code=303)
        if not any(vs.is_required for vs in vacancy.skills):
            return RedirectResponse("/admin/vacancies?msg=no_required", status_code=303)
        if vacancy.deadline and vacancy.deadline < date.today():
            return RedirectResponse("/admin/vacancies?msg=past_deadline", status_code=303)
        vacancy.status = "published"
        if not vacancy.published_at:  # keep the date of the first publication
            vacancy.published_at = datetime.utcnow()
        vacancy.rejection_reason = None
        log_action(db, admin, "approve_vacancy", "vacancy", vacancy.id)
        db.commit()
        return RedirectResponse("/admin/vacancies?msg=approved", status_code=303)
    finally:
        db.close()


@router.post("/admin/vacancy/{vacancy_id}/reject")
def reject_vacancy(request: Request, vacancy_id: int, reason: str = Form("")):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        vacancy = db.get(Vacancy, vacancy_id)
        if not vacancy:
            raise HTTPException(status_code=404, detail="Vacancy not found")
        if vacancy.status != "pending":
            return RedirectResponse("/admin/vacancies", status_code=303)
        reason = reason.strip()
        if not reason:
            return RedirectResponse("/admin/vacancies?msg=reason_required", status_code=303)
        vacancy.status = "rejected"
        vacancy.rejection_reason = reason[:1000]
        log_action(db, admin, "reject_vacancy", "vacancy", vacancy.id, reason[:1000])
        db.commit()
        return RedirectResponse("/admin/vacancies?msg=rejected", status_code=303)
    finally:
        db.close()


def target_label(db, target_type, target_id):
    """Human-readable name of the object an action was applied to."""
    if target_type == "vacancy":
        item = db.get(Vacancy, target_id)
        return item.title if item else f"vacancy #{target_id}"
    if target_type == "company":
        item = db.get(EmployerProfile, target_id)
        return item.company_name if item else f"company #{target_id}"
    if target_type == "user":
        item = db.get(User, target_id)
        return item.email if item else f"user #{target_id}"
    return f"{target_type} #{target_id}"


@router.get("/admin/users")
def admin_users(request: Request, msg: str = ""):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        users = db.query(User).filter(User.role != "admin").order_by(User.id.desc()).all()
        return templates.TemplateResponse(request, "admin_users.html",
                                          {"users": users, "msg": msg})
    finally:
        db.close()


def set_user_blocked(request, user_id, value, reason=""):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        user = db.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if user.role == "admin":  # administrators cannot be blocked here
            return RedirectResponse("/admin/users", status_code=303)
        if user.is_blocked != value:
            user.is_blocked = value
            log_action(db, admin, "block_user" if value else "unblock_user",
                       "user", user.id, reason.strip()[:1000] or None)
            db.commit()
        return RedirectResponse("/admin/users?msg=" + ("blocked" if value else "unblocked"),
                                status_code=303)
    finally:
        db.close()


@router.post("/admin/user/{user_id}/block")
def block_user(request: Request, user_id: int, reason: str = Form("")):
    return set_user_blocked(request, user_id, True, reason)


@router.post("/admin/user/{user_id}/unblock")
def unblock_user(request: Request, user_id: int):
    return set_user_blocked(request, user_id, False)


@router.get("/admin/log")
def admin_log(request: Request):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        entries = db.query(ModerationLog).order_by(ModerationLog.id.desc()).limit(200).all()
        rows = []
        for e in entries:
            actor = db.get(User, e.admin_id)
            rows.append({
                "entry": e,
                "admin": actor.email if actor else "—",
                "target": target_label(db, e.target_type, e.target_id),
            })
        return templates.TemplateResponse(request, "admin_log.html", {"rows": rows})
    finally:
        db.close()

from database import ProjectSkill, Skill, SkillAlias, StudentSkill, VacancySkill


def clean_name(value):
    return " ".join((value or "").split())[:60]


def name_taken(db, name, ignore_skill_id=None):
    """True if a skill name or a synonym with this text already exists (case-insensitive)."""
    lowered = name.lower()
    for s in db.query(Skill):
        if s.id != ignore_skill_id and s.name.lower() == lowered:
            return True
    for a in db.query(SkillAlias):
        if a.alias.lower() == lowered:
            return True
    return False


def skills_redirect(msg):
    return RedirectResponse(f"/admin/skills?msg={msg}", status_code=303)


@router.get("/admin/skills")
def admin_skills(request: Request, msg: str = ""):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        rows = []
        for s in db.query(Skill).order_by(Skill.name).all():
            rows.append({
                "skill": s, "aliases": s.aliases,
                "vacancies": db.query(VacancySkill).filter_by(skill_id=s.id).count(),
                "students": db.query(StudentSkill).filter_by(skill_id=s.id).count(),
                "projects": db.query(ProjectSkill).filter_by(skill_id=s.id).count(),
            })
        return templates.TemplateResponse(request, "admin_skills.html",
                                          {"rows": rows, "msg": msg})
    finally:
        db.close()


@router.post("/admin/skills/add")
def add_skill(request: Request, name: str = Form("")):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        name = clean_name(name)
        if not name:
            return skills_redirect("empty")
        if name_taken(db, name):
            return skills_redirect("exists")
        skill = Skill(name=name)
        db.add(skill)
        db.flush()
        log_action(db, admin, "add_skill", "skill", skill.id, name)
        db.commit()
        return skills_redirect("added")
    finally:
        db.close()


@router.post("/admin/skills/{skill_id}/rename")
def rename_skill(request: Request, skill_id: int, name: str = Form("")):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        skill = db.get(Skill, skill_id)
        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")
        name = clean_name(name)
        if not name:
            return skills_redirect("empty")
        if name == skill.name:
            return skills_redirect("renamed")
        if name_taken(db, name, ignore_skill_id=skill.id):
            return skills_redirect("exists")
        old = skill.name
        skill.name = name
        log_action(db, admin, "rename_skill", "skill", skill.id, f"{old} -> {name}")
        db.commit()
        return skills_redirect("renamed")
    finally:
        db.close()


@router.post("/admin/skills/{skill_id}/alias")
def add_alias(request: Request, skill_id: int, alias: str = Form("")):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        skill = db.get(Skill, skill_id)
        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")
        alias = clean_name(alias)
        if not alias:
            return skills_redirect("empty")
        if name_taken(db, alias):
            return skills_redirect("exists")
        db.add(SkillAlias(skill_id=skill.id, alias=alias))
        log_action(db, admin, "add_alias", "skill", skill.id, f"{skill.name}: {alias}")
        db.commit()
        return skills_redirect("alias_added")
    finally:
        db.close()


@router.post("/admin/alias/{alias_id}/delete")
def delete_alias(request: Request, alias_id: int):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        alias = db.get(SkillAlias, alias_id)
        if not alias:
            raise HTTPException(status_code=404, detail="Synonym not found")
        log_action(db, admin, "delete_alias", "skill", alias.skill_id,
                   f"{alias.skill.name}: {alias.alias}")
        db.delete(alias)
        db.commit()
        return skills_redirect("alias_deleted")
    finally:
        db.close()


@router.post("/admin/skills/{skill_id}/delete")
def delete_skill(request: Request, skill_id: int):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        skill = db.get(Skill, skill_id)
        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")
        in_use = (db.query(VacancySkill).filter_by(skill_id=skill.id).count()
                  + db.query(StudentSkill).filter_by(skill_id=skill.id).count()
                  + db.query(ProjectSkill).filter_by(skill_id=skill.id).count())
        if in_use:
            return skills_redirect("in_use")
        log_action(db, admin, "delete_skill", "skill", skill.id, skill.name)
        for a in list(skill.aliases):
            db.delete(a)
        db.delete(skill)
        db.commit()
        return skills_redirect("deleted")
    finally:
        db.close()

    from database import Direction


def directions_redirect(msg):
    return RedirectResponse(f"/admin/directions?msg={msg}", status_code=303)


def direction_taken(db, name, ignore_id=None):
    lowered = name.lower()
    return any(d.id != ignore_id and d.name.lower() == lowered
               for d in db.query(Direction))


@router.get("/admin/directions")
def admin_directions(request: Request, msg: str = ""):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        rows = []
        for d in db.query(Direction).order_by(Direction.id).all():
            rows.append({
                "direction": d,
                "vacancies": db.query(Vacancy).filter_by(direction=d.name).count(),
                "students": db.query(User).filter_by(direction=d.name).count(),
            })
        return templates.TemplateResponse(request, "admin_directions.html",
                                          {"rows": rows, "msg": msg})
    finally:
        db.close()


@router.post("/admin/directions/add")
def add_direction(request: Request, name: str = Form("")):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        name = clean_name(name)
        if not name:
            return directions_redirect("empty")
        if direction_taken(db, name):
            return directions_redirect("exists")
        direction = Direction(name=name)
        db.add(direction)
        db.flush()
        log_action(db, admin, "add_direction", "direction", direction.id, name)
        db.commit()
        return directions_redirect("added")
    finally:
        db.close()


@router.post("/admin/directions/{direction_id}/rename")
def rename_direction(request: Request, direction_id: int, name: str = Form("")):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        direction = db.get(Direction, direction_id)
        if not direction:
            raise HTTPException(status_code=404, detail="Direction not found")
        name = clean_name(name)
        if not name:
            return directions_redirect("empty")
        if name == direction.name:
            return directions_redirect("renamed")
        if direction_taken(db, name, ignore_id=direction.id):
            return directions_redirect("exists")
        old = direction.name
        # vacancies and student profiles store the direction name, so they are updated too
        db.query(Vacancy).filter_by(direction=old).update(
            {"direction": name}, synchronize_session=False)
        db.query(User).filter_by(direction=old).update(
            {"direction": name}, synchronize_session=False)
        direction.name = name
        log_action(db, admin, "rename_direction", "direction", direction.id,
                   f"{old} -> {name}")
        db.commit()
        return directions_redirect("renamed")
    finally:
        db.close()


@router.post("/admin/directions/{direction_id}/delete")
def delete_direction(request: Request, direction_id: int):
    db = SessionLocal()
    try:
        admin = get_admin(request, db)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        direction = db.get(Direction, direction_id)
        if not direction:
            raise HTTPException(status_code=404, detail="Direction not found")
        in_use = (db.query(Vacancy).filter_by(direction=direction.name).count()
                  + db.query(User).filter_by(direction=direction.name).count())
        if in_use:
            return directions_redirect("in_use")
        log_action(db, admin, "delete_direction", "direction", direction.id, direction.name)
        db.delete(direction)
        db.commit()
        return directions_redirect("deleted")
    finally:
        db.close()