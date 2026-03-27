import os
import json
import shutil
from typing import List
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from database import engine, get_db, Base
import models
import analysis

# Create DB tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Audit Evidence Copilot")

import tempfile

# Ensure upload dir exists
UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def read_index():
    return FileResponse("static/index.html")

# --- Controls endpoints ---
@app.post("/api/controls/")
def create_control(description: str = Form(...), test_procedure: str = Form(...), db: Session = Depends(get_db)):
    db_control = models.Control(description=description, test_procedure=test_procedure)
    db.add(db_control)
    db.commit()
    db.refresh(db_control)
    return db_control

@app.get("/api/controls/")
def get_controls(db: Session = Depends(get_db)):
    return db.query(models.Control).all()

@app.get("/api/controls/{control_id}")
def get_control(control_id: int, db: Session = Depends(get_db)):
    control = db.query(models.Control).filter(models.Control.id == control_id).first()
    if not control:
        raise HTTPException(status_code=404, detail="Control not found")
    return control

# --- Test Runs endpoints ---
@app.post("/api/test_runs/")
def create_test_run(
    control_id: int = Form(...), 
    files: List[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    saved_files = []
    if files:
        for file in files:
            if not file.filename: continue
            file_path = os.path.join(UPLOAD_DIR, file.filename)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            saved_files.append(file_path)
    
    db_run = models.TestRun(
        control_id=control_id,
        files_json=json.dumps(saved_files),
        status="Pending"
    )
    db.add(db_run)
    db.commit()
    db.refresh(db_run)
    return db_run

@app.get("/api/test_runs/")
def get_test_runs(control_id: int = None, db: Session = Depends(get_db)):
    query = db.query(models.TestRun)
    if control_id:
        query = query.filter(models.TestRun.control_id == control_id)
    return query.all()

@app.get("/api/test_runs/{run_id}")
def get_test_run(run_id: int, db: Session = Depends(get_db)):
    run = db.query(models.TestRun).filter(models.TestRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Test Run not found")
    return run

class WorkpaperUpdate(BaseModel):
    workpaper: str

@app.put("/api/test_runs/{run_id}/workpaper")
def update_workpaper(run_id: int, payload: WorkpaperUpdate, db: Session = Depends(get_db)):
    run = db.query(models.TestRun).filter(models.TestRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Test Run not found")
    run.workpaper = payload.workpaper
    db.commit()
    return {"message": "Success"}

@app.post("/api/test_runs/{run_id}/analyze")
def analyze_test_run(run_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    run = db.query(models.TestRun).filter(models.TestRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Test Run not found")
    
    control = db.query(models.Control).filter(models.Control.id == run.control_id).first()
    files = json.loads(run.files_json) if run.files_json else []
    
    run.status = "Analyzing..."
    db.commit()
    
    def background_analysis(run_id: int, control_dict: dict, file_list: list):
        # We need a new db session for the background task
        bg_db = next(get_db())
        try:
            results = analysis.analyze_evidence(run_id, control_dict, file_list)
            bg_run = bg_db.query(models.TestRun).filter(models.TestRun.id == run_id).first()
            bg_run.status = "Analyzed"
            bg_run.summary = json.dumps(results["files"]) # Storing array of file dicts in summary column to keep schema same
            bg_run.checklist_json = json.dumps(results["checklist"])
            bg_run.rating = results["sufficiency"]
            bg_run.issues = json.dumps(results["issues"])
            bg_run.workpaper = results["workpaper_text"]
            bg_db.commit()
        except Exception as e:
            bg_run = bg_db.query(models.TestRun).filter(models.TestRun.id == run_id).first()
            bg_run.status = "Error"
            bg_run.issues = f"Analysis Failed: {str(e)}"
            bg_db.commit()
        finally:
            bg_db.close()

    control_dict = {"description": control.description, "test_procedure": control.test_procedure}
    background_tasks.add_task(background_analysis, run_id, control_dict, files)
    
    return {"message": "Analysis started in background"}


# --- Dev Helpers ---
@app.get("/api/dev/generate_sample")
def generate_sample_data():
    """Generates a sample CSV and PDF for easy JML testing and returns as a ZIP file."""
    import pandas as pd
    from reportlab.pdfgen import canvas
    import random
    import io
    import zipfile
    
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        # 1. Generate Users CSV (50 rows)
        roles = ["Developer", "Analyst", "Manager", "Admin", "Support"]
        users_data = []
        for i in range(1, 51):
            users_data.append({
                "user_id": f"U{i:03d}",
                "role": random.choice(roles),
                "created_date": f"2023-{random.randint(1,12):02d}-01",
                "terminated_date": "",
                "active": "Yes"
            })
        df_users = pd.DataFrame(users_data)
        zip_file.writestr("sample_users.csv", df_users.to_csv(index=False))
        
        # 2. Generate HR Leavers CSV (10 rows)
        leavers_data = []
        for i in range(51, 61):
            # Safe random ranges to avoid month end overflows
            m = random.randint(1,12)
            d = random.randint(1,20)
            term_date = f"2023-{m:02d}-{d:02d}"
            
            # Make the first one a late leaver (> 24 hours)
            if i == 51:
                access_date = f"2023-{m:02d}-{d+5:02d}"
            else:
                access_date = term_date
                
            leavers_data.append({
                "employee_id": f"U{i:03d}",
                "name": f"Terminated Employee {i}",
                "termination_date": term_date,
                "access_removed_date": access_date
            })
        df_leavers = pd.DataFrame(leavers_data)
        zip_file.writestr("sample_hr_leavers.csv", df_leavers.to_csv(index=False))
        
        # 3. Generate PDF
        pdf_buffer = io.BytesIO()
        c = canvas.Canvas(pdf_buffer)
        c.drawString(100, 750, "IT Service Desk Ticket: REQ-99214")
        c.drawString(100, 730, "Requestor: hiring.manager@company.com")
        c.drawString(100, 710, "Requested For: U001")
        c.drawString(100, 690, "Type: New Hire Onboarding - Developer Access")
        c.drawString(100, 670, "Date: 2023-01-01")
        c.drawString(100, 630, "Approval Status: APPROVED")
        c.drawString(100, 610, "Approved By: IT Director")
        c.save()
        zip_file.writestr("sample_approval.pdf", pdf_buffer.getvalue())
        
    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=sample_evidence.zip"}
    )

@app.get("/api/dev/sample_jml_csv")
def get_sample_jml_csv():
    import pandas as pd
    import random
    import io
    import zipfile
    
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        roles = ["Developer", "Analyst", "Manager", "Admin", "Support"]
        
        # 1. users.csv (Population)
        users_data = []
        for i in range(1, 101):
            users_data.append({
                "user_id": f"U{i:03d}",
                "role": random.choice(roles),
                "hire_date": f"2023-{random.randint(1,6):02d}-01",
                "active": "Yes"
            })
        df_users = pd.DataFrame(users_data)
        zip_file.writestr("users.csv", df_users.to_csv(index=False))
        
        # 2. leavers.csv (Termination List)
        leavers_data = []
        for i in range(101, 111):
            m = random.randint(7,12)
            d = random.randint(1,20)
            term_date = f"2023-{m:02d}-{d:02d}"
            
            if i == 101:
                access_date = f"2023-{m:02d}-{d+3:02d}" # Late leaver
            else:
                access_date = term_date
                
            leavers_data.append({
                "user_id": f"U{i:03d}",
                "termination_date": term_date,
                "access_removed_date": access_date,
                "active": "No"
            })
        df_leavers = pd.DataFrame(leavers_data)
        zip_file.writestr("leavers.csv", df_leavers.to_csv(index=False))
        
        # 3. approvals.txt (Audit Evidence)
        txt_content = (
            "IT Service Desk Ticket: REQ-10492\n"
            "Requestor: HR Operations Team\n"
            "Type: User Onboarding / Lifecycle Sync\n"
            "Status: APPROVED by IT Director (John Smith)\n"
            "Date: 2023-01-01\n"
            "Summary: Batch hire for Q1 growth."
        )
        zip_file.writestr("approvals.txt", txt_content)
        
    zip_buffer.seek(0)
    
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=sox_itgc_sample.zip"}
    )

@app.post("/api/test_runs/{run_id}/export_pdf") 
# @app.post("/api/test_runs/{run_id}/export_pdf")
# def export_workpaper_pdf(run_id: int, payload: WorkpaperUpdate):
#     ...
#     return Response(...)

def export_workpaper_pdf(run_id: int, payload: WorkpaperUpdate, db: Session = Depends(get_db)):
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.colors import HexColor
    import io

    # Fetch run/control details for the header
    run = db.query(models.TestRun).filter(models.TestRun.id == run_id).first()
    control = db.query(models.Control).filter(models.Control.id == run.control_id).first()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)
    styles = getSampleStyleSheet()
    
    # Custom Styles
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=18, textColor=HexColor('#1E40AF'), spaceAfter=12)
    header_style = ParagraphStyle('HeaderStyle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, textColor=HexColor('#64748B'), spaceAfter=4)
    content_bold = ParagraphStyle('ContentBold', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, spaceAfter=6)
    body_style = ParagraphStyle('BodyStyle', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=14, spaceAfter=10)

    Story = []
    
    # Header Section
    Story.append(Paragraph("SOX ITGC Evidence Evaluation Report", title_style))
    Story.append(HRFlowable(width="100%", thickness=1, color=HexColor('#E2E8F0'), spaceBefore=2, spaceAfter=20))
    
    Story.append(Paragraph("CONTROL DETAILS", header_style))
    Story.append(Paragraph(f"<b>Control ID:</b> {control.id}", body_style))
    Story.append(Paragraph(f"<b>Description:</b> {control.description}", body_style))
    Story.append(Spacer(1, 12))
    
    Story.append(Paragraph("TEST EXECUTION METADATA", header_style))
    Story.append(Paragraph(f"<b>Run ID:</b> {run.id}", body_style))
    Story.append(Paragraph(f"<b>Status:</b> {run.status}", body_style))
    Story.append(Paragraph(f"<b>Rating:</b> {run.rating.replace('_', ' ').upper() if run.rating else 'PENDING'}", body_style))
    Story.append(Paragraph(f"<b>Execution Date:</b> {run.created_at.strftime('%B %d, %Y %H:%M:%S UTC') if run.created_at else 'N/A'}", body_style))
    
    Story.append(Spacer(1, 20))
    Story.append(Paragraph("EVALUATION NARRATIVE & WORKPAPER", header_style))
    Story.append(HRFlowable(width="100%", thickness=1, color=HexColor('#F1F5F9'), spaceBefore=4, spaceAfter=12))
    
    # Formatting the workpaper text
    text = payload.workpaper.replace('\r\n', '\n')
    paras = text.split('\n')
    for p in paras:
        if not p.strip():
            Story.append(Spacer(1, 8))
            continue
            
        import re
        p_escaped = p.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        # Convert **text** to <b>text</b>
        p_formatted = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', p_escaped)
        # Convert - list item to bullet
        if p_formatted.strip().startswith('- '):
            p_formatted = "&bull; " + p_formatted.strip()[2:]
            
        Story.append(Paragraph(p_formatted, body_style))
    
    doc.build(Story)
    buffer.seek(0)
    
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=SOX_ITGC_Report_Run_{run_id}.pdf"}
    )
