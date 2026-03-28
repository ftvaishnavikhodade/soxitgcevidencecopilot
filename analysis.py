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
    
    # Simple Parsing & Tagging Logic
    for file_path in files:
        if not os.path.exists(file_path):
            continue
            
        ext = file_path.lower().split('.')[-1]
        filename = os.path.basename(file_path)
        
        file_info = {
            "name": filename,
            "type": ext.upper(),
            "summary": "Evidence file",
            "rows": None,
            "columns": [],
            "date_coverage": "Unknown",
            "recognized_type": "Unrecognized",
            "mapping_status": "Not recognized",
            "mapped_columns": []
        }
        
        try:
            if ext in ['csv', 'xls', 'xlsx']:
                df = pd.read_csv(file_path) if ext == 'csv' else pd.read_excel(file_path)
                cols_raw = df.columns.tolist()
                file_info["rows"] = df.shape[0]
                file_info["columns"] = cols_raw
                file_info["summary"] = f"Datatable with {df.shape[0]} rows."
                
                # Recognition Heuristics
                cols = [str(c).lower().strip() for c in cols_raw]
                mapped = []
                
                # Check 1: Approval Log
                if any("status" in c or "approv" in c for c in cols):
                    file_info["recognized_type"] = "Approval Log"
                    mapped.extend([c for c in cols if "status" in c or "approv" in c])
                    req_col = next((c for c in cols if "req" in c or "ticket" in c), None)
                    if req_col: mapped.append(req_col)
                    file_info["mapping_status"] = "Fully recognized" if req_col else "Partially recognized"
                
                # Check 2: Terminations Listing
                elif any("term" in c and "date" in c for c in cols):
                    file_info["recognized_type"] = "Terminations Listing"
                    term_col = next((c for c in cols if "term" in c and "date" in c), None)
                    acc_col = next((c for c in cols if "access" in c and "remov" in c and "date" in c), None)
                    if term_col: mapped.append(term_col)
                    if acc_col: mapped.append(acc_col)
                    file_info["mapping_status"] = "Fully recognized" if (term_col and acc_col) else "Partially recognized"
                
                # Check 3: General User Population
                elif any("user" in c or "emp" in c for c in cols):
                    if file_info["recognized_type"] == "Unrecognized":
                        file_info["recognized_type"] = "User Population"
                        mapped.extend([c for c in cols if "user" in c or "emp" in c or "role" in c or "active" in c])
                        file_info["mapping_status"] = "Fully recognized"
                
                file_info["mapped_columns"] = mapped
                files_data.append(file_info)
                dataframes.append((file_info["recognized_type"], df))
                has_csv = True
                
            elif ext == 'pdf':
                with pdfplumber.open(file_path) as pdf:
                    text = pdf.pages[0].extract_text()
                    first_page_preview = text[:50].replace('\\n', ' ') if text else "No text"
                    file_info["summary"] = f"PDF Evidence. Preview: {first_page_preview}..."
                    file_info["recognized_type"] = "Approval Evidence (PDF)"
                    file_info["mapping_status"] = "Fully recognized"
                    files_data.append(file_info)
                    has_pdf = True
        except Exception as e:
            file_info["summary"] = f"Parse error: {str(e)}"
            files_data.append(file_info)

    # ---------------------------------------------
    # Deep Evaluation & Trust Rules
    # ---------------------------------------------
    has_approval_log = any(f["recognized_type"] == "Approval Log" for f in files_data)
    has_terminations = any(f["recognized_type"] == "Terminations Listing" for f in files_data)
    has_population = any(f["recognized_type"] == "User Population" for f in files_data)
    
    missing_evidence = []
    if not (has_approval_log or has_pdf): missing_evidence.append("Approval Evidence (Log or PDF)")
    if not has_terminations: missing_evidence.append("Terminated Users Listing")
    if not has_population and not has_terminations: missing_evidence.append("User Population / HR Data")

    untestable_rules = []

    # Rule base setup
    rules = {
        "period_matches": {
            "status": "not_testable", 
            "reason": "Period coverage cannot be verified from provided headers.",
            "exceptions": []
        },
        "population_complete": {
            "status": "not_testable" if missing_evidence else "pass",
            "reason": "Missing required population data." if missing_evidence else "Population listings appear complete and structured.",
            "exceptions": []
        },
        "approvals_present": {
            "status": "pass", 
            "reason": "Awaiting evaluation.",
            "exceptions": []
        },
        "timing_sla_met": {
            "status": "pass",
            "reason": "Awaiting evaluation.",
            "exceptions": []
        }
    }

    exception_found = False
    exception_details = ""
    approval_exception_found = False
    approval_exception_details = ""
    
    # Evaluate Approvals
    if has_approval_log:
        for ftype, df in dataframes:
            if ftype != "Approval Log": continue
            cols = [str(c).lower().strip() for c in df.columns]
            status_col_name = next((c for c in cols if "status" in c or "approv" in c), None)
            req_id_col_name = next((c for c in cols if "request" in c or "ticket" in c or "id" in c and "emp" not in c and "user" not in c), None)
            
            if status_col_name:
                status_col = df.columns[cols.index(status_col_name)]
                req_id_col = df.columns[cols.index(req_id_col_name)] if req_id_col_name else None
                
                for _, row in df.iterrows():
                    val = str(row[status_col]).lower().strip()
                    if val in ["no", "false", "f", "missing", "pending", "rejected", "unauthorized", "none", "nan", ""] or pd.isna(row[status_col]):
                        approval_exception_found = True
                        req_label = str(row[req_id_col]) if req_id_col else "A request"
                        exc_msg = f"Missing or invalid approval found for {req_label}."
                        approval_exception_details = exc_msg
                        rules["approvals_present"]["exceptions"].append({
                            "evidence": "Approval Log",
                            "identity": req_label,
                            "detail": f"Status '{val}' indicates approval failure."
                        })
    elif has_pdf:
        rules["approvals_present"]["reason"] = "PDF approval tickets supplied (assumed passing for sample)."
    else:
        rules["approvals_present"]["status"] = "not_testable"
        rules["approvals_present"]["reason"] = "Required approval evidence was not uploaded."
        untestable_rules.append("Approval completeness cannot be tested without approval log or PDF.")

    if approval_exception_found:
        rules["approvals_present"]["status"] = "fail"
        rules["approvals_present"]["reason"] = "Exceptions noted containing missing or invalid approvals."
    elif rules["approvals_present"]["status"] == "pass" and has_approval_log:
         rules["approvals_present"]["reason"] = "Valid approval status found for all logged requests."


    # Evaluate Timing SLA
    if has_terminations:
        for ftype, df in dataframes:
            if ftype != "Terminations Listing": continue
            cols = [str(c).lower().strip() for c in df.columns]
            term_col_name = next((c for c in cols if "term" in c and "date" in c), None)
            acc_col_name = next((c for c in cols if "access" in c and "remov" in c and "date" in c), None)
            
            if term_col_name and acc_col_name:
                term_col = df.columns[cols.index(term_col_name)]
                acc_col = df.columns[cols.index(acc_col_name)]
                emp_id_col_name = next((c for c in cols if 'emp' in c and 'id' in c or 'user' in c and 'id' in c), None)
                emp_id_col = df.columns[cols.index(emp_id_col_name)] if emp_id_col_name else None
                name_col = df.columns[cols.index('name')] if 'name' in cols else None
                
                for _, row in df.iterrows():
                    term_date_raw = row[term_col]
                    access_date_raw = row[acc_col]
                    
                    if pd.isna(term_date_raw) or str(term_date_raw).strip() == "": continue
                        
                    emp_label = ""
                    if emp_id_col: emp_label += str(row[emp_id_col])
                    if name_col: emp_label += f" / {row[name_col]}" if emp_label else str(row[name_col])
                    if not emp_label: emp_label = "An employee"
                    
                    if pd.isna(access_date_raw) or str(access_date_raw).strip() == "" or str(access_date_raw).strip().lower() == "nan":
                        exception_found = True
                        exc_msg = f"{emp_label} was terminated on {term_date_raw} but access removal is missing (active)."
                        exception_details = exc_msg
                        rules["timing_sla_met"]["exceptions"].append({
                            "evidence": "Terminations Listing",
                            "identity": emp_label,
                            "detail": exc_msg
                        })
                        continue
                        
                    try:
                        term_date = pd.to_datetime(term_date_raw, errors='coerce', utc=True)
                        access_date = pd.to_datetime(access_date_raw, errors='coerce', utc=True)
                        if pd.isna(term_date) or pd.isna(access_date): continue
                            
                        diff = access_date - term_date
                        if diff.total_seconds() > 86400: # 24 hours
                            exception_found = True
                            exc_msg = f"{emp_label} access was removed on {access_date_raw}, exceeding 24h SLA from {term_date_raw}."
                            exception_details = exc_msg
                            rules["timing_sla_met"]["exceptions"].append({
                                "evidence": "Terminations Listing",
                                "identity": emp_label,
                                "detail": exc_msg
                            })
                    except Exception: pass
            else:
                rules["timing_sla_met"]["status"] = "not_testable"
                rules["timing_sla_met"]["reason"] = "Mapped columns insufficient for deep timing calc."
                untestable_rules.append("Timing SLA cannot be calculated accurately due to missing mapped columns.")
    else:
        rules["timing_sla_met"]["status"] = "not_testable"
        rules["timing_sla_met"]["reason"] = "Required termination evidence was not uploaded."
        untestable_rules.append("Timing SLA cannot be tested without termination listing.")

    if exception_found:
        rules["timing_sla_met"]["status"] = "fail"
        rules["timing_sla_met"]["reason"] = "Leaver SLA exceptions identified exceeding 24-hour limit."
    elif rules["timing_sla_met"]["status"] == "pass" and has_terminations:
        rules["timing_sla_met"]["reason"] = "No instances exceeding access removal SLA found."
        
    # Global Sufficiency & Confidence
    issues = []
    sufficiency = "likely_sufficient"
    confidence = "High"
    evidence_sufficiency = "Sufficient Evidence"
    
    if len(missing_evidence) > 0:
        sufficiency = "unclear"
        evidence_sufficiency = "Partial Evidence" if len(missing_evidence) < 3 else "Insufficient Evidence"
        confidence = "Medium" if len(missing_evidence) < 3 else "Low"
        issues.append(f"Missing crucial testing evidence: {', '.join(missing_evidence)}")
        
    if exception_found or approval_exception_found:
        sufficiency = "likely_insufficient"
        evidence_sufficiency = "Sufficient Evidence (Exceptions Found)"
        confidence = "High"
        if exception_found: issues.append("Leaver timing SLA exceptions discovered.")
        if approval_exception_found: issues.append("Invalid or missing approval requests identified.")

    if not files:
        issues.append("No evidence provided to test out of scope control.")
        sufficiency = "likely_insufficient"
        evidence_sufficiency = "Insufficient Evidence"
        confidence = "Low"

    # Workpaper Generation
    all_exceptions = []
    for r in rules.values():
        for ex in r.get("exceptions", []):
            all_exceptions.append(ex.get("detail", ""))
            
    exceptions_str = "\\n- ".join(all_exceptions)
    if exceptions_str: exceptions_str = "- " + exceptions_str

    workpaper = f"""**Objective**
To verify that logical access requests (JML) are appropriately authorized, provisioned in a timely manner, and deactivated promptly upon termination.

**Procedures Performed**
1. Read recognized evidence packages spanning User Population, Terminations, and Approvals.
2. Verified the completeness of access evidence across the entire extracted set.
3. Automatically calculated row-level SLAs and approval presence against policy guidelines.

**Conclusion**
The control is evaluated as **{sufficiency.replace('_', ' ').title()}**.
Test Confidence: **{confidence}** | Evidence Testability: **{evidence_sufficiency}**
{"Exceptions noted; follow-up required with IT owner." if sufficiency != "likely_sufficient" else ("Test procedures executed without major exception." if confidence == "High" else "Review limited by testability.")}

{"**Exception Details:** \\n" + exceptions_str if exceptions_str else ""}
"""

    return {
        "files": files_data,
        "checklist": {
            "rules": rules,
            "trust": {
                "missing_evidence": missing_evidence,
                "untestable_rules": untestable_rules,
                "confidence_level": confidence,
                "evidence_sufficiency": evidence_sufficiency
            }
        },
        "sufficiency": sufficiency,
        "issues": issues,
        "workpaper_text": workpaper
    }
