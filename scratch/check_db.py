from database import SessionLocal
import models

db = SessionLocal()
runs = db.query(models.TestRun).filter(models.TestRun.status == 'Analyzed').all()
print(f"Found {len(runs)} analyzed runs.")
for r in runs:
    print(f"ID: {r.id}, Name: {r.name}, Control: {r.control_id}, Rating: {r.rating}")
db.close()
