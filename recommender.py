from collections import Counter

from database import Vacancy

# Weights from the technical specification (section 11)
WEIGHTS = {"E": 0.60, "D": 0.15, "A": 0.15, "F": 0.05, "L": 0.05}


def score_vacancy(vacancy, user_skills, direction, work_format, city):
    required = [vs.skill.name for vs in vacancy.skills if vs.is_required]
    optional = [vs.skill.name for vs in vacancy.skills if not vs.is_required]

    matched_req = [s for s in required if s in user_skills]
    missing_req = [s for s in required if s not in user_skills]
    matched_opt = [s for s in optional if s in user_skills]

    # Only applicable components take part in the score
    components = {}
    if required:
        components["E"] = len(matched_req) / len(required)
    if optional:
        components["D"] = len(matched_opt) / len(optional)
    if direction:
        components["A"] = 1.0 if vacancy.direction == direction else 0.0
    if work_format:
        components["F"] = 1.0 if vacancy.work_format == work_format else 0.0
    if city:
        remote = vacancy.work_format == "Remote"
        same_city = (vacancy.city or "").strip().lower() == city.strip().lower()
        components["L"] = 1.0 if (remote or same_city) else 0.0

    # Remaining weights are normalized to sum to 1
    total_weight = sum(WEIGHTS[k] for k in components)
    if total_weight:
        score = 100 * sum(WEIGHTS[k] * v for k, v in components.items()) / total_weight
    else:
        score = 0.0

    return {
        "vacancy": vacancy,
        "score": round(score, 1),
        "matched_req": matched_req,
        "missing_req": missing_req,
        "matched_opt": matched_opt,
        "required_total": len(required),
        "direction_match": components.get("A") == 1.0,
        "explanation": build_explanation(vacancy, matched_req, missing_req,
                                         matched_opt, required, components),
    }


def join_names(names):
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def build_explanation(vacancy, matched_req, missing_req, matched_opt, required, components):
    parts = []
    if required:
        text = f"Matched {len(matched_req)} of {len(required)} required skills"
        if matched_req:
            text += f": {join_names(matched_req)}"
        parts.append(text + ".")
    if missing_req:
        label = "Missing skill" if len(missing_req) == 1 else "Missing skills"
        parts.append(f"{label}: {join_names(missing_req)}.")
    if matched_opt:
        parts.append(f"Nice-to-have skills matched: {join_names(matched_opt)}.")
    if components.get("A") == 1.0:
        parts.append(f"The direction {vacancy.direction} matches your interests.")
    return " ".join(parts)


def get_recommendations(db, user):
    user_skills = {ss.skill.name for ss in user.student_skills}
    if not user.direction or not user_skills:
        return {"ready": False, "results": [], "learn": []}

    vacancies = db.query(Vacancy).filter(Vacancy.status == "published").all()
    results = [score_vacancy(v, user_skills, user.direction, user.work_format, user.city)
               for v in vacancies]
    # Highest score first; on a tie the newer vacancy goes first
    results.sort(key=lambda r: (-r["score"], -r["vacancy"].id))

    # "What to learn": missing skills in active vacancies of the chosen direction
    counter = Counter()
    for v in vacancies:
        if v.direction == user.direction:
            names = {vs.skill.name for vs in v.skills}
            counter.update(names - user_skills)
    learn = counter.most_common(8)

    return {"ready": True, "results": results, "learn": learn}