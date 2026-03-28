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
    
    # Deterministic Dataframe Evaluation for Timings and Approvals
    timing_sla_met = "unclear"
    exception_found = False
    exception_details = ""
    valid_timing_eval = False
    
    has_approval_evidence = has_pdf
    approval_exception_found = False
    approval_exception_details = ""
    
    if has_csv:
        for df in dataframes:
            cols = [str(c).lower().strip() for c in df.columns]
            
            # 1. Approval Evaluation
            status_col_name = next((c for c in cols if "status" in c or "approv" in c), None)
            if status_col_name:
                has_approval_evidence = True
                status_col = df.columns[cols.index(status_col_name)]
                req_id_col_name = next((c for c in cols if "request" in c or "ticket" in c or "id" in c and "emp" not in c and "user" not in c), None)
                req_id_col = df.columns[cols.index(req_id_col_name)] if req_id_col_name else None
                
                for _, row in df.iterrows():
                    val = str(row[status_col]).lower().strip()
                    if val in ["missing", "pending", "rejected", "unauthorized", "none", "nan", ""] or pd.isna(row[status_col]):
                        approval_exception_found = True
                        req_label = str(row[req_id_col]) if req_id_col else "A request"
                        approval_exception_details = f"Exceptions noted in approval log: {req_label} is missing valid approval."
                        break
                        
            # 2. Timing Evaluation
            if 'termination_date' in cols and 'access_removed_date' in cols:
                valid_timing_eval = True
                if timing_sla_met == "unclear":
                    timing_sla_met = "pass" # Start assuming pass if we have data to check
                
                term_col = df.columns[cols.index('termination_date')]
                acc_col = df.columns[cols.index('access_removed_date')]
                emp_id_col_name = next((c for c in cols if 'emp' in c and 'id' in c or 'user' in c and 'id' in c), None)
                emp_id_col = df.columns[cols.index(emp_id_col_name)] if emp_id_col_name else None
                name_col = df.columns[cols.index('name')] if 'name' in cols else None
                
                for _, row in df.iterrows():
                    term_date_raw = row[term_col]
                    access_date_raw = row[acc_col]
                    
                    if pd.isna(term_date_raw) or str(term_date_raw).strip() == "":
                        continue
                        
                    emp_label = ""
                    if emp_id_col: emp_label += str(row[emp_id_col])
                    if name_col: 
                        if emp_label: emp_label += f" / {row[name_col]}"
                        else: emp_label += str(row[name_col])
                    if not emp_label: emp_label = "An employee"
                    
                    # Missing access removal date when terminated -> FAIL
                    if pd.isna(access_date_raw) or str(access_date_raw).strip() == "" or str(access_date_raw).strip().lower() == "nan":
                        timing_sla_met = "fail"
                        exception_found = True
                        exception_details = f"1 leaver exception identified. {emp_label} was terminated on {term_date_raw} but access removal date is missing (potentially still active)."
                        break
                        
                    try:
                        term_date = pd.to_datetime(term_date_raw, errors='coerce', utc=True)
                        access_date = pd.to_datetime(access_date_raw, errors='coerce', utc=True)
                        
                        if pd.isna(term_date) or pd.isna(access_date):
                            continue
                            
                        diff = access_date - term_date
                        
                        if diff.total_seconds() > 86400: # 24 hours
                            timing_sla_met = "fail"
                            exception_found = True
                            exception_details = f"1 leaver exception identified. {emp_label} was terminated on {term_date_raw} and access was removed on {access_date_raw}, exceeding the 24-hour requirement."
                            break
                    except Exception:
                        pass
            
            # Continue checking other dataframes in case one fails on approvals and another fails on timing
            
        checklist["timing_sla_met"] = timing_sla_met

    # Synthesize Issues and Conclusion
    if not has_csv:
        issues.append("Missing population / user listing file (CSV/Excel).")
        sufficiency = "likely_insufficient"
        checklist["population_complete"] = "fail"
    
    if not has_approval_evidence:
        issues.append("Missing approval evidence.")
        checklist["approvals_present"] = "fail"
        sufficiency = "likely_insufficient"
    elif approval_exception_found:
        issues.append(approval_exception_details)
        checklist["approvals_present"] = "fail"
        sufficiency = "likely_insufficient"
        
    if exception_found:
        issues.append(exception_details)
        sufficiency = "likely_insufficient"
        
    if has_csv and has_approval_evidence and not exception_found and not approval_exception_found:
        sufficiency = "likely_sufficient"
        
    if valid_timing_eval and not exception_found:
        issues.append("No exceptions found in leaver timing SLA based on CSV analysis.")
    elif not valid_timing_eval and has_csv:
        issues.append("No valid leaver timing columns (termination_date / access_removed_date) found in CSV analysis.")
        checklist["timing_sla_met"] = "unclear"
        
    if not files:
         issues.append("No evidence provided to test the control.")
         sufficiency = "likely_insufficient"
         checklist = {
            "period_matches": "unclear",
            "population_complete": "fail",
            "approvals_present": "fail",
            "timing_sla_met": "unclear"
         }

    # Prepare Workpaper Narrative
    all_exceptions = []
    if exception_found: all_exceptions.append(exception_details)
    if approval_exception_found: all_exceptions.append(approval_exception_details)
    exceptions_str = " ".join(all_exceptions)

    workpaper = f"""**Objective**
To verify that logical access requests (JML) are appropriately authorized, provisioned in a timely manner, and deactivated promptly upon termination.

**Procedures Performed**
1. Obtained the user population and termination listings.
2. Verified the presence of approval evidence for access requests.
3. Traced access removal dates against the HR termination dates to ensure logical access was revoked within the required SLA.

**Conclusion**
The control is evaluated as **{sufficiency.replace('_', ' ').title()}**. 
{"Exceptions noted; follow-up required with IT owner." if sufficiency != "likely_sufficient" else "Test procedures executed without major exception."}

{"**Exception Details:** " + exceptions_str if exceptions_str else ""}
"""

    return {
        "files": files_data,
        "checklist": checklist,
        "sufficiency": sufficiency,
        "issues": issues,
        "workpaper_text": workpaper
    }
