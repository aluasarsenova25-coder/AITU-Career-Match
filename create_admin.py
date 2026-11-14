from getpass import getpass

from database import Base, SessionLocal, User, engine
from security import hash_password

Base.metadata.create_all(engine)

email = input("Admin email: ").strip().lower()
password = getpass("Admin password (min. 8 characters): ")
if "@" not in email or len(password) < 8:
    raise SystemExit("Invalid email or the password is too short.")

db = SessionLocal()
user = db.query(User).filter_by(email=email).first()
if user:
    user.role = "admin"
    user.password_hash = hash_password(password)
    print("Existing account is now an admin.")
else:
    db.add(User(email=email, password_hash=hash_password(password),
                first_name="Admin", last_name="", role="admin"))
    print("Admin account created.")
db.commit()
db.close()