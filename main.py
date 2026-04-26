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

class RunRename(BaseModel):
    name: str

@app.patch("/api/test_runs/{run_id}/rename")
def rename_test_run(run_id: int, payload: RunRename, db: Session = Depends(get_db)):
    run = db.query(models.TestRun).filter(models.TestRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Test Run not found")
    run.name = payload.name.strip()[:100]  # cap at 100 chars
    db.commit()
    db.refresh(run)
    return run

@app.post("/api/test_runs/{run_id}/analyze")
def analyze_test_run(run_id: int, db: Session = Depends(get_db)):
    run = db.query(models.TestRun).filter(models.TestRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Test Run not found")
    
    control = db.query(models.Control).filter(models.Control.id == run.control_id).first()
    files = json.loads(run.files_json) if run.files_json else []
    
    run.status = "Analyzing..."
    db.commit()
    
    control_dict = {"description": control.description, "test_procedure": control.test_procedure}
    
    # Run synchronously because Vercel Serverless halts background tasks immediately after response
    try:
        results = analysis.analyze_evidence(run_id, control_dict, files)
        run.status = "Analyzed"
        run.summary = json.dumps(results["files"]) 
        run.checklist_json = json.dumps(results["checklist"])
        run.rating = results["sufficiency"]
        run.issues = json.dumps(results["issues"])
        run.workpaper = results["workpaper_text"]
        db.commit()
    except Exception as e:
        run.status = "Error"
        run.issues = f"Analysis Failed: {str(e)}"
        db.commit()
    
    return {"message": "Analysis completed"}


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
    from reportlab.lib.enums import TA_CENTER
    body_textColor = HexColor('#334155')
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=24, textColor=HexColor('#2563EB'), spaceAfter=4)
    subtitle_style = ParagraphStyle('SubTitle', parent=styles['Normal'], fontName='Helvetica', fontSize=11, textColor=HexColor('#64748B'), spaceAfter=24)
    header_style = ParagraphStyle('HeaderStyle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=14, textColor=HexColor('#0F172A'), spaceBefore=18, spaceAfter=8)
    body_style = ParagraphStyle('BodyStyle', parent=styles['Normal'], fontName='Helvetica', fontSize=12, leading=18, textColor=body_textColor, spaceAfter=8)
    section_title_style = ParagraphStyle('SectionTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=14, textColor=HexColor('#0F172A'))
    body_center_style = ParagraphStyle('BodyCenter', parent=body_style, alignment=TA_CENTER)

    Story = []
    
    # Header Section
    Story.append(Paragraph("SOX ITGC Evidence Evaluation Report", title_style))
    Story.append(Paragraph("Generated by Audit Copilot Engine", subtitle_style))
    Story.append(HRFlowable(width="100%", thickness=1, color=HexColor('#E2E8F0'), spaceBefore=2, spaceAfter=18))
    
    # Details layout via Table for better alignment
    from reportlab.platypus import Table, TableStyle
    
    exec_date = run.created_at.strftime('%B %d, %Y %H:%M:%S UTC') if run.created_at else 'N/A'
    meta_data = [
        [Paragraph("<b>Control ID:</b>", body_center_style), Paragraph(str(control.id), body_center_style), Paragraph("<b>Run ID:</b>", body_center_style), Paragraph(str(run.id), body_center_style)],
        [Paragraph("<b>Status:</b>", body_center_style), Paragraph(run.status, body_center_style), Paragraph("<b>Rating:</b>", body_center_style), Paragraph(run.rating.replace('_', ' ').title() if run.rating else 'Pending', body_center_style)],
        [Paragraph("<b>Execution:</b>", body_center_style), Paragraph(exec_date, body_center_style), "", ""]
    ]
    t_meta = Table(meta_data, colWidths=[80, 160, 60, 168])
    t_meta.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('TOPPADDING', (0,0), (-1,-1), 10),
        ('INNERGRID', (0,0), (-1,-1), 0.5, HexColor('#E2E8F0')),
        ('BOX', (0,0), (-1,-1), 0.5, HexColor('#94A3B8')),
    ]))
    
    Story.append(Paragraph("EVALUATION METADATA", header_style))
    Story.append(t_meta)
    
    # Control Description centered structural block
    Story.append(Spacer(1, 14))
    desc_label_style = ParagraphStyle('DescLabel', parent=body_center_style, fontSize=9, textColor=HexColor('#64748B'))
    desc_table = Table(
        [
            [Paragraph("<b>CONTROL DESCRIPTION</b>", desc_label_style)],
            [Paragraph(control.description, body_center_style)]
        ], 
        colWidths=[468]
    )
    desc_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('TOPPADDING', (0,0), (-1,-1), 10),
        ('BACKGROUND', (0,0), (-1,0), HexColor('#F8FAFC')),
        ('BOX', (0,0), (-1,-1), 0.5, HexColor('#E2E8F0')),
        ('INNERGRID', (0,0), (-1,-1), 0.5, HexColor('#E2E8F0')),
    ]))
    Story.append(desc_table)
    Story.append(Spacer(1, 24))
    
    # ------------------ VISUAL SUMMARY CHARTS ------------------
    try:
        import json
        from reportlab.platypus import KeepTogether, Table
        from reportlab.graphics.shapes import Drawing, String
        from reportlab.graphics.charts.piecharts import Pie

        checklist_data = json.loads(run.checklist_json) if run.checklist_json else {}
        rules_data = checklist_data.get("rules", checklist_data) if isinstance(checklist_data, dict) else {}
        files_data = json.loads(run.summary) if run.summary else []
        trust_data = checklist_data.get("trust", {}) if isinstance(checklist_data, dict) else {}
        missing_evidence = trust_data.get("missing_evidence", [])

        # Evidence Coverage
        count_fully = sum(1 for f in files_data if f.get("mapping_status") == "Fully recognized")
        count_partially = sum(1 for f in files_data if f.get("mapping_status") == "Partially recognized")
        count_missing = len(missing_evidence)
        ev_all = [(count_fully, "Fully Recognized", HexColor('#10B981')), 
                  (count_partially, "Partially Recognized", HexColor('#F59E0B')), 
                  (count_missing, "Missing Evidence", HexColor('#EF4444'))]
        ev_data = []
        ev_labels = []
        ev_colors = []
        for d, l, c in ev_all:
            if d > 0:
                ev_data.append(d)
                ev_labels.append(l)
                ev_colors.append(c)

        # Testing Outcomes
        c_pass = 0
        c_fail = 0
        c_not_testable = 0
        c_unclear = 0
        for k, v in rules_data.items():
            status = v.get("status") if isinstance(v, dict) else v
            if status == "pass": c_pass += 1
            elif status == "fail": c_fail += 1
            elif status == "not_testable": c_not_testable += 1
            else: c_unclear += 1
        test_all = [(c_pass, "Pass", HexColor('#10B981')), 
                    (c_fail, "Review Required", HexColor('#EF4444')), 
                    (c_not_testable, "Not Testable", HexColor('#94A3B8')), 
                    (c_unclear, "Unclear Evidence", HexColor('#F59E0B'))]
        test_data = []
        test_labels = []
        test_colors = []
        for d, l, c in test_all:
            if d > 0:
                test_data.append(d)
                test_labels.append(l)
                test_colors.append(c)

        def make_pie_with_legend(data, labels, colors, title):
            from reportlab.graphics.charts.legends import Legend
            from reportlab.graphics.charts.piecharts import Pie3d
            d = Drawing(260, 160)
            
            pc = Pie3d()
            pc.x = 10
            pc.y = 25
            pc.width = 110
            pc.height = 80
            pc.data = list(data)
            pc.slices.strokeWidth = 0.5
            pc.slices.strokeColor = HexColor('#FFFFFF')
            for i, c in enumerate(colors):
                pc.slices[i].fillColor = c
            d.add(pc)
            
            leg = Legend()
            leg.x = 140
            leg.y = 105
            leg.dy = 16
            leg.fontName = 'Helvetica'
            leg.fontSize = 9
            leg.boxAnchor = 'nw'
            leg.colorNamePairs = [(colors[i], f'{labels[i]} ({data[i]})') for i in range(len(data))]
            leg.strokeWidth = 0
            d.add(leg)
            
            d.add(String(120, 145, title, textAnchor='middle', fontName='Helvetica-Bold', fontSize=10, fillColor=HexColor('#0F172A')))
            return d

        charts = []
        if test_data:
            charts.append(make_pie_with_legend(test_data, test_labels, test_colors, "Testing Outcomes"))
        if ev_data:
            charts.append(make_pie_with_legend(ev_data, ev_labels, ev_colors, "Evidence Coverage"))

        if charts:
            Story.append(Paragraph("VISUAL SUMMARY", header_style))
            Story.append(HRFlowable(width="100%", thickness=1, color=HexColor('#E2E8F0'), spaceBefore=2, spaceAfter=8))
            if len(charts) == 2:
                Story.append(KeepTogether([Table([charts], colWidths=[260, 260])]))
            else:
                Story.append(KeepTogether(charts))

    except Exception as e:
        print(f"Error generating charts: {e}")
    # -----------------------------------------------------------

    from reportlab.platypus import PageBreak
    Story.append(PageBreak())

    Story.append(Paragraph("EVALUATION NARRATIVE & WORKPAPER", header_style))
    Story.append(HRFlowable(width="100%", thickness=1, color=HexColor('#E2E8F0'), spaceBefore=2, spaceAfter=12))
    
    # Formatting the workpaper text
    text = payload.workpaper.replace('\r\n', '\n')
    paras = text.split('\n')
    
    # Use a small indented style for bullets
    bullet_style = ParagraphStyle('BulletStyle', parent=body_style, leftIndent=16, spaceBefore=2, spaceAfter=2)
    
    in_table = False
    table_data = []

    for i, p in enumerate(paras):
        if not p.strip() and not in_table:
            Story.append(Spacer(1, 4))
            continue
            
        is_table_row = p.strip().startswith('|') and p.strip().endswith('|')
        
        if is_table_row:
            in_table = True
            cols = [col.strip() for col in p.strip().strip('|').split('|')]
            if all(col.replace('-', '').strip() == '' for col in cols): continue
            
            row_paras = []
            for col in cols:
                if len(table_data) == 0:
                    row_paras.append(Paragraph(f"<b>{col}</b>", ParagraphStyle('TH', parent=body_style, alignment=TA_CENTER, textColor=HexColor('#FFFFFF'), fontSize=9)))
                else:
                    row_paras.append(Paragraph(col, ParagraphStyle('TD', parent=body_style, alignment=TA_CENTER, fontSize=9)))
            table_data.append(row_paras)
            
            # End of table check
            if (i + 1 == len(paras)) or not paras[i+1].strip().startswith('|'):
                num_cols = len(table_data[0]) if table_data else 1
                t = Table(table_data, colWidths=[468.0 / num_cols] * num_cols)
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,0), HexColor('#475569')),
                    ('TEXTCOLOR', (0,0), (-1,0), HexColor('#FFFFFF')),
                    ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                    ('INNERGRID', (0,0), (-1,-1), 0.5, HexColor('#E2E8F0')),
                    ('BOX', (0,0), (-1,-1), 0.5, HexColor('#94A3B8')),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 10),
                    ('TOPPADDING', (0,0), (-1,-1), 10),
                ]))
                Story.append(t)
                in_table = False
                table_data = []
            continue
            
        import re
        p_escaped = p.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        # Convert **text** to clean section headers
        if p_escaped.startswith('**') and p_escaped.endswith('**') and len(p_escaped) > 4:
            clean_head = p_escaped[2:-2]
            Story.append(Spacer(1, 8))
            Story.append(Paragraph(clean_head, section_title_style))
            Story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor('#F1F5F9'), spaceBefore=2, spaceAfter=4))
            continue
            
        p_formatted = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', p_escaped)
        
        # Convert - list item to bullet
        if p_formatted.strip().startswith('- '):
            p_formatted = "&bull; " + p_formatted.strip()[2:]
            Story.append(Paragraph(p_formatted, bullet_style))
        else:
            Story.append(Paragraph(p_formatted, body_style))
    def add_page_number(canvas, doc):
        page_num = canvas.getPageNumber()
        text = f"Page {page_num}"
        canvas.saveState()
        canvas.setFont('Helvetica', 9)
        canvas.setFillColor(HexColor('#64748B'))
        canvas.drawRightString(doc.pagesize[0] - 72, 36, text)
        canvas.restoreState()

    doc.build(Story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    buffer.seek(0)
    
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=SOX_ITGC_Report_Run_{run_id}.pdf"}
    )
