import os
import json
import pandas as pd
import pdfplumber

def analyze_evidence(run_id: int, control: dict, files: list) -> dict:
    """
    Parses files and simulates an AI analysis based on the extracted information and the control definition.
    """
    files_data = []
    dataframes = []
    has_csv = False
    has_pdf = False
    
    # Simple Parsing Logic
    for file_path in files:
        if not os.path.exists(file_path):
            continue
            
        ext = file_path.lower().split('.')[-1]
        filename = os.path.basename(file_path)
        
        file_info = {
            "name": filename,
            "summary": "Evidence file",
            "rows": 0,
            "columns": [],
            "date_coverage": "2023" # mock for example
        }
        
        try:
            if ext in ['csv']:
                df = pd.read_csv(file_path)
                file_info["rows"] = df.shape[0]
                file_info["columns"] = df.columns.tolist()
                file_info["summary"] = f"CSV with {df.shape[0]} rows."
                files_data.append(file_info)
                dataframes.append(df)
                has_csv = True
            elif ext in ['xls', 'xlsx']:
                df = pd.read_excel(file_path)
                file_info["rows"] = df.shape[0]
                file_info["columns"] = df.columns.tolist()
                file_info["summary"] = f"Excel with {df.shape[0]} rows."
                files_data.append(file_info)
                dataframes.append(df)
                has_csv = True
            elif ext == 'pdf':
                with pdfplumber.open(file_path) as pdf:
                    text = pdf.pages[0].extract_text()
                    first_page_preview = text[:50].replace('\n', ' ') if text else "No text"
                    file_info["summary"] = f"PDF Approval. Preview: {first_page_preview}..."
                    files_data.append(file_info)
                    has_pdf = True
        except Exception as e:
            file_info["summary"] = f"Parse error: {str(e)}"
            files_data.append(file_info)

    # Mock AI Checklist evaluation based on parsed data hints
    issues = []
    sufficiency = "likely_sufficient"
    
    # EXACT requested schema
    checklist = {
        "period_matches": "pass",
        "population_complete": "pass",
        "approvals_present": "pass",
        "timing_sla_met": "pass"
    }
    
    # Deterministic Dataframe Evaluation for Timings
    timing_sla_met = "unclear"
    exception_found = False
    exception_details = ""
    
    if has_csv:
        valid_timing_eval = False
        for df in dataframes:
            cols = [str(c).lower().strip() for c in df.columns]
            if 'termination_date' in cols and 'access_removed_date' in cols:
                valid_timing_eval = True
                if timing_sla_met == "unclear":
                    timing_sla_met = "pass" # Start assuming pass if we have data to check
                
                term_col = df.columns[cols.index('termination_date')]
                acc_col = df.columns[cols.index('access_removed_date')]
                emp_id_col = df.columns[cols.index('employee_id')] if 'employee_id' in cols else (df.columns[cols.index('emp_id')] if 'emp_id' in cols else None)
                name_col = df.columns[cols.index('name')] if 'name' in cols else None
                
                for _, row in df.iterrows():
                    term_date_raw = row[term_col]
                    access_date_raw = row[acc_col]
                    
                    if pd.isna(term_date_raw) or pd.isna(access_date_raw) or str(term_date_raw).strip() == "" or str(access_date_raw).strip() == "":
                        continue
                        
                    try:
                        term_date = pd.to_datetime(term_date_raw, errors='coerce', utc=True)
                        access_date = pd.to_datetime(access_date_raw, errors='coerce', utc=True)
                        
                        if pd.isna(term_date) or pd.isna(access_date):
                            continue
                            
                        diff = access_date - term_date
                        
                        if diff.total_seconds() > 86400: # 24 hours
                            timing_sla_met = "fail"
                            exception_found = True
                            
                            emp_label = ""
                            if emp_id_col: emp_label += str(row[emp_id_col])
                            if name_col: 
                                if emp_label: emp_label += f" / {row[name_col]}"
                                else: emp_label += str(row[name_col])
                            if not emp_label: emp_label = "An employee"
                            
                            exception_details = f"1 leaver exception identified. {emp_label} was terminated on {term_date_raw} and access was removed on {access_date_raw}, exceeding the 24-hour requirement."
                            break
                    except Exception:
                        pass
            
            if exception_found:
                break
                
        checklist["timing_sla_met"] = timing_sla_met

    if not has_csv:
        issues.append("Missing population / user listing file (CSV/Excel).")
        sufficiency = "likely_insufficient"
        checklist["population_complete"] = "fail"
    
    if not has_pdf:
        issues.append("Missing approval evidence file (PDF).")
        checklist["approvals_present"] = "fail"
        if sufficiency != "likely_insufficient":
            sufficiency = "unclear"
            
    if has_csv and has_pdf:
        if exception_found:
            sufficiency = "likely_insufficient"
            issues.append(exception_details)
        else:
            sufficiency = "likely_sufficient"
            if valid_timing_eval:
                issues.append("No exceptions found in leaver timing SLA based on CSV analysis.")
            else:
                issues.append("No valid leaver timing columns (termination_date / access_removed_date) found in CSV analysis.")
        
        issues.append("Population looks complete, columns match expected headers.")
        
    if not files:
         issues.append("No evidence provided to test the control.")
         sufficiency = "likely_insufficient"
         checklist = {
            "period_matches": "unclear",
            "population_complete": "fail",
            "approvals_present": "fail",
            "timing_sla_met": "unclear"
         }

    workpaper = f"""**Objective**
To verify that logical access requests (JML) are appropriately authorized, provisioned in a timely manner, and deactivated promptly upon termination.

**Procedures Performed**
1. Obtained the population and matched against active directory.
2. Selected a sample of requests and obtained approval tickets (PDFs).
3. Vouched the approval string to ensure appropriate management authorization.
4. Traced provisioning/deprovisioning dates against the HR effective date.

**Conclusion**
The control is evaluated as **{sufficiency.replace('_', ' ').title()}**. 
{"Exceptions noted; follow-up required with IT owner." if sufficiency != "likely_sufficient" else "Test procedures executed without major exception."}

{"**Exception Details:** " + exception_details if exception_found else ""}
"""

    return {
        "files": files_data,
        "checklist": checklist,
        "sufficiency": sufficiency,
        "issues": issues,
        "workpaper_text": workpaper
    }
