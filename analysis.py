import os
import json
import pandas as pd
import pdfplumber


# ---------------------------------------------------------------------------
# Control-type detection helpers
# ---------------------------------------------------------------------------

DEPROV_KEYWORDS = [
    "terminat", "deprovisio", "leaver", "offboard", "deactivat",
    "revoke", "remov", "disable", "separation", "exit",
]

PROV_KEYWORDS = [
    "provision", "onboard", "new hire", "access request", "grant",
    "joiner", "new user", "new employee", "access grant", "request",
    "authorized", "approval", "ticket",
]


def _detect_control_type(control: dict) -> str:
    """Return 'deprovisioning' or 'provisioning' based on the control text."""
    text = (
        (control.get("description") or "") + " " + (control.get("test_procedure") or "")
    ).lower()

    deprov_score = sum(1 for kw in DEPROV_KEYWORDS if kw in text)
    prov_score = sum(1 for kw in PROV_KEYWORDS if kw in text)

    if deprov_score > prov_score:
        return "deprovisioning"
    return "provisioning"  # default


# ---------------------------------------------------------------------------
# File recognition helpers
# ---------------------------------------------------------------------------

def _classify_csv(cols_raw, filename_lower, control_type):
    """Classify a CSV/Excel file based on its column names and filename."""
    cols = [str(c).lower().strip() for c in cols_raw]
    mapped = []
    recognized_type = "Unrecognized"
    mapping_status = "Not recognized"

    # --- Access Request / Ticket Log ---
    is_request = (
        any("request" in c or "ticket" in c or "req" in c for c in cols)
        and any("status" in c or "approv" in c or "state" in c for c in cols)
    )
    if is_request:
        recognized_type = "Access Request Log"
        mapped.extend([c for c in cols if any(k in c for k in ["request", "ticket", "req", "status", "approv", "state"])])
        mapping_status = "Fully recognized"
        return recognized_type, mapping_status, mapped

    # --- Approval Log (status column without explicit request ID) ---
    is_approval = any("approv" in c for c in cols) and any("status" in c or "date" in c for c in cols)
    if is_approval:
        recognized_type = "Approval Log"
        mapped.extend([c for c in cols if "status" in c or "approv" in c or "date" in c])
        req_col = next((c for c in cols if "req" in c or "ticket" in c), None)
        if req_col:
            mapped.append(req_col)
        mapping_status = "Fully recognized" if req_col else "Partially recognized"
        return recognized_type, mapping_status, mapped

    # --- Terminations Listing ---
    is_term = any("term" in c and "date" in c for c in cols)
    if is_term:
        recognized_type = "Terminations Listing"
        term_col = next((c for c in cols if "term" in c and "date" in c), None)
        acc_col = next((c for c in cols if "access" in c and "remov" in c and "date" in c), None)
        if term_col:
            mapped.append(term_col)
        if acc_col:
            mapped.append(acc_col)
        mapping_status = "Fully recognized" if (term_col and acc_col) else "Partially recognized"
        return recognized_type, mapping_status, mapped

    # --- Access Listing / Granted Access ---
    is_access = (
        any("access" in c or "entitlement" in c or "permission" in c or "privilege" in c for c in cols)
        or any("role" in c and ("user" in c2 or "emp" in c2) for c in cols for c2 in cols)
    )
    if is_access and not is_term:
        recognized_type = "Access Listing"
        mapped.extend([c for c in cols if any(k in c for k in ["access", "role", "entitlement", "permission", "privilege", "user", "emp", "system", "app"])])
        mapping_status = "Fully recognized"
        return recognized_type, mapping_status, mapped

    # --- Org Chart / Reporting Structure ---
    is_org = (
        any("manager" in c or "report" in c or "dept" in c or "department" in c for c in cols)
        and any("name" in c or "emp" in c or "user" in c for c in cols)
        and not any("status" in c or "approv" in c for c in cols)
    )
    if is_org or "org" in filename_lower:
        recognized_type = "Org Chart / Role Context"
        mapped.extend([c for c in cols if any(k in c for k in ["manager", "report", "dept", "department", "name", "emp", "title"])])
        mapping_status = "Fully recognized"
        return recognized_type, mapping_status, mapped

    # --- General User Population ---
    is_population = any("user" in c or "emp" in c for c in cols)
    if is_population:
        recognized_type = "User Population"
        mapped.extend([c for c in cols if "user" in c or "emp" in c or "role" in c or "active" in c])
        mapping_status = "Fully recognized"
        return recognized_type, mapping_status, mapped

    return recognized_type, mapping_status, mapped


def _classify_pdf(text_preview, filename_lower):
    """Classify a PDF based on its first-page text and filename."""
    preview = (text_preview or "").lower()
    fn = filename_lower

    # 1. Access Listing (Highest priority for Provisioning completeness)
    if any(kw in fn for kw in ["access_listing", "user_access", "netsuite", "sap_listing", "granted", "entitlement"]):
        return "Access Listing (PDF)", "Fully recognized"
    if any(kw in preview for kw in ["user listing", "access listing", "permissions report", "netsuite user", "sap master"]):
        return "Access Listing (PDF)", "Partially recognized"

    # 2. Org chart / reporting structure
    if any(kw in fn for kw in ["org_chart", "org chart", "orgchart", "reporting_structure"]):
        return "Org Chart / Role Context (PDF)", "Fully recognized"
    if any(kw in preview for kw in ["org chart", "organization chart", "reporting structure"]):
        return "Org Chart / Role Context (PDF)", "Partially recognized"

    # 3. Approval evidence
    if any(kw in fn for kw in ["approval", "authorized", "authorized_by"]):
        return "Approval Evidence (PDF)", "Fully recognized"
    if any(kw in preview for kw in ["approv", "authorized", "sign-off"]):
        return "Approval Evidence (PDF)", "Fully recognized"

    # 4. Access request ticket
    if any(kw in fn for kw in ["request", "ticket", "req-", "req#"]):
        return "Access Request Ticket (PDF)", "Fully recognized"
    if any(kw in preview for kw in ["request", "ticket", "req-", "req#", "service desk"]):
        return "Access Request Ticket (PDF)", "Fully recognized"

    # 5. Terminations Listing (Added for Deprovisioning)
    if any(kw in fn for kw in ["terminated", "leaver", "separation", "exit", "offboard"]):
        return "Terminations Listing (PDF)", "Fully recognized"
    if any(kw in preview for kw in ["terminated users", "employee separation", "access removal log", "leaver report"]):
        return "Terminations Listing (PDF)", "Partially recognized"

    return "Supporting Document (PDF)", "Partially recognized"


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------

def analyze_evidence(run_id: int, control: dict, files: list) -> dict:
    """
    Parses files and evaluates evidence based on the control definition.
    The analysis adapts its rules, required evidence, and exception logic
    depending on whether the control is provisioning or deprovisioning.
    """
    control_type = _detect_control_type(control)

    files_data = []
    dataframes = []
    has_csv = False
    has_pdf = False

    # ------------------------------------------------------------------
    # Parse & classify uploaded files
    # ------------------------------------------------------------------
    for file_path in files:
        if not os.path.exists(file_path):
            continue

        ext = file_path.lower().split('.')[-1]
        filename = os.path.basename(file_path)
        filename_lower = filename.lower()

        file_info = {
            "name": filename,
            "type": ext.upper(),
            "summary": "Evidence file",
            "rows": None,
            "columns": [],
            "date_coverage": "Unknown",
            "recognized_type": "Unrecognized",
            "mapping_status": "Not recognized",
            "mapped_columns": [],
        }

        try:
            if ext in ["csv", "xls", "xlsx"]:
                df = pd.read_csv(file_path) if ext == "csv" else pd.read_excel(file_path)
                cols_raw = df.columns.tolist()
                file_info["rows"] = df.shape[0]
                file_info["columns"] = cols_raw
                file_info["summary"] = f"Datatable with {df.shape[0]} rows."

                rec_type, map_status, mapped = _classify_csv(cols_raw, filename_lower, control_type)
                file_info["recognized_type"] = rec_type
                file_info["mapping_status"] = map_status
                file_info["mapped_columns"] = mapped

                files_data.append(file_info)
                dataframes.append((rec_type, df))
                has_csv = True

            elif ext == "pdf":
                with pdfplumber.open(file_path) as pdf:
                    text = pdf.pages[0].extract_text() if pdf.pages else ""
                    first_page_preview = text[:200] if text else "No text"
                    file_info["summary"] = f"PDF Evidence. Preview: {(text or '')[:50].replace(chr(10), ' ')}..."

                    rec_type, map_status = _classify_pdf(first_page_preview, filename_lower)
                    file_info["recognized_type"] = rec_type
                    file_info["mapping_status"] = map_status

                    files_data.append(file_info)
                    has_pdf = True
        except Exception as e:
            file_info["summary"] = f"Parse error: {str(e)}"
            files_data.append(file_info)

    # ------------------------------------------------------------------
    # Convenience flags — Standardized across CSV and PDF
    # ------------------------------------------------------------------
    has_approval_log = any(f["recognized_type"] == "Approval Log" for f in files_data)
    has_request_log = any(f["recognized_type"] == "Access Request Log" for f in files_data)
    
    # Check for PDF or generic matches
    has_request_doc = any("Request" in f["recognized_type"] for f in files_data)
    has_approval_doc = any("Approval" in f["recognized_type"] for f in files_data)
    has_listing_doc = any("Access Listing" in f["recognized_type"] for f in files_data)
    
    has_terminations = any("Terminations" in f["recognized_type"] for f in files_data)
    has_population = any("Population" in f["recognized_type"] for f in files_data)
    has_org_chart = any("Org Chart" in f["recognized_type"] for f in files_data)

    has_any_approval = has_approval_doc
    has_any_request = has_request_doc
    has_any_listing = has_listing_doc or has_population

    missing_evidence = []
    untestable_rules = []

    if control_type == "provisioning":
        if not has_any_request:
            missing_evidence.append("Access Request / Ticket Evidence")
        if not has_any_approval:
            missing_evidence.append("Approval Evidence (Log or PDF)")
        if not has_any_listing:
            missing_evidence.append("Access Listing / Granted Access Evidence")
    else:  # deprovisioning
        if not has_terminations:
            missing_evidence.append("Terminated Users Listing")
        if not has_any_approval:
            missing_evidence.append("Approval Evidence (Log or PDF)")
        if not has_any_listing:
            missing_evidence.append("User Population / HR Data")

    # ------------------------------------------------------------------
    # Build rules — depends on control type
    # ------------------------------------------------------------------
    if control_type == "provisioning":
        rules = _build_provisioning_rules(
            files_data, dataframes,
            has_any_request, has_any_approval, has_approval_log,
            has_request_log, has_listing_doc, has_population,
            has_pdf, missing_evidence, untestable_rules,
        )
    else:
        rules = _build_deprovisioning_rules(
            files_data, dataframes,
            has_any_approval, has_approval_log,
            has_terminations, has_population,
            has_pdf, missing_evidence, untestable_rules,
        )

    # ------------------------------------------------------------------
    # Global sufficiency & confidence
    # ------------------------------------------------------------------
    issues = []
    sufficiency = "likely_sufficient"
    confidence = "High"
    evidence_sufficiency = "Sufficient Evidence"

    any_exception = any(
        r.get("status") == "fail" for r in rules.values()
    )

    if len(missing_evidence) > 0:
        sufficiency = "unclear"
        evidence_sufficiency = "Partial Evidence" if len(missing_evidence) < 3 else "Insufficient Evidence"
        confidence = "Medium" if len(missing_evidence) < 3 else "Low"
        issues.append(f"Missing evidence: {', '.join(missing_evidence)}")

    if any_exception:
        sufficiency = "likely_insufficient"
        evidence_sufficiency = "Sufficient Evidence (Exceptions Found)"
        confidence = "High"
        for rname, rdata in rules.items():
            if rdata["status"] == "fail":
                for ex in rdata.get("exceptions", []):
                    issues.append(ex.get("detail", ""))

    if not files:
        issues.append("No evidence provided.")
        sufficiency = "likely_insufficient"
        evidence_sufficiency = "Insufficient Evidence"
        confidence = "Low"

    # ------------------------------------------------------------------
    # Workpaper generation
    # ------------------------------------------------------------------
    all_exceptions = []
    for r in rules.values():
        for ex in r.get("exceptions", []):
            all_exceptions.append(ex.get("detail", ""))

    exceptions_log = "\n- ".join(all_exceptions)
    if exceptions_log:
        exceptions_log = "- " + exceptions_log
    else:
        exceptions_log = "No material exceptions or limitations noted."

    ctrl_desc = control.get("description", "N/A")
    ctrl_proc = control.get("test_procedure", "N/A")
    type_label = control_type.replace("_", " ").title()

    evidence_names = ", ".join([f.get("name", "Unknown File") for f in files_data]) if files_data else "None provided"
    missing_evidence_list = ", ".join(missing_evidence) if missing_evidence else "None identified"

    testing_performed_lines = []
    for r_name, r_val in rules.items():
        status_label = str(r_val.get("status", "Unknown")).upper()
        testing_performed_lines.append(f"- {r_name.replace('_', ' ').title()}: {status_label}")
    testing_performed_str = "\n".join(testing_performed_lines)

    # Draft Conclusion formatting
    if all_exceptions:
        conc_text = "The procedures were executed with exceptions noted. Follow-up is required."
    elif sufficiency != "likely_sufficient" and missing_evidence:
        conc_text = "Unable to reach a confident conclusion due to missing or insufficient evidence."
    elif sufficiency == "unclear":
        conc_text = "Review is limited by evidence testability. Partial or unclear evidence prevented a complete evaluation."
    else:
        conc_text = "Testing procedures executed without material exception based on the evidence provided."

    workpaper = f"""**Control Objective**
{ctrl_desc}

**Audit Procedure Performed**
{ctrl_proc}

**Evidence Reviewed**
- Files Analyzed: {evidence_names}
- Missing Expected Evidence: {missing_evidence_list}

**Testing Performed**
{testing_performed_str}

**Results Summary**
- Evaluation: {sufficiency.replace('_', ' ').title()}
- Test Confidence: {confidence}
- Evidence Testability: {evidence_sufficiency}

**Exceptions / Limitations**
{exceptions_log}

**Draft Conclusion**
{conc_text}

**Reviewer Notes**
[Leave your review notes here...]
"""

    return {
        "files": files_data,
        "checklist": {
            "rules": rules,
            "trust": {
                "missing_evidence": missing_evidence,
                "untestable_rules": untestable_rules,
                "confidence_level": confidence,
                "evidence_sufficiency": evidence_sufficiency,
            },
        },
        "sufficiency": sufficiency,
        "issues": issues,
        "workpaper_text": workpaper,
    }


# =====================================================================
# PROVISIONING rules
# =====================================================================

def _build_provisioning_rules(
    files_data, dataframes,
    has_any_request, has_any_approval, has_approval_log,
    has_request_log, has_any_listing, has_population,
    has_pdf, missing_evidence, untestable_rules,
):
    rules = {
        "request_documented": {
            "status": "not_testable",
            "reason": "Awaiting evaluation.",
            "exceptions": [],
        },
        "approvals_present": {
            "status": "not_testable",
            "reason": "Awaiting evaluation.",
            "exceptions": [],
        },
        "access_granted_matches": {
            "status": "not_testable",
            "reason": "Awaiting evaluation.",
            "exceptions": [],
        },
        "population_complete": {
            "status": "not_testable" if missing_evidence else "pass",
            "reason": (
                "Missing required evidence to verify population."
                if missing_evidence
                else "Evidence population appears complete."
            ),
            "exceptions": [],
        },
    }

    crit_labels_map = {
        "request_documented": "Request Documented",
        "approvals_present": "Approvals Present",
        "access_granted_matches": "Granted Access Matches Request",
        "population_complete": "Population Complete",
    }

    # --- Evaluate: Request Documented ---
    if has_request_log:
        rules["request_documented"]["status"] = "pass"
        rules["request_documented"]["reason"] = "Access request log provided with request identifiers."
        # Check for missing request IDs
        for ftype, df in dataframes:
            if ftype != "Access Request Log":
                continue
            cols = [str(c).lower().strip() for c in df.columns]
            req_col_name = next((c for c in cols if "request" in c or "ticket" in c or "req" in c), None)
            if req_col_name:
                req_col = df.columns[cols.index(req_col_name)]
                for _, row in df.iterrows():
                    val = row[req_col]
                    if pd.isna(val) or str(val).strip() in ["", "nan", "none"]:
                        rules["request_documented"]["status"] = "fail"
                        rules["request_documented"]["reason"] = "One or more rows have missing request identifiers."
                        rules["request_documented"]["exceptions"].append({
                            "evidence": "Access Request Log",
                            "identity": f"Row index {_}",
                            "detail": "Access request entry with missing or blank request identifier.",
                        })
    elif has_pdf:
        rules["request_documented"]["status"] = "pass"
        rules["request_documented"]["reason"] = "PDF ticket(s) supplied as request documentation."
    else:
        rules["request_documented"]["status"] = "not_testable"
        rules["request_documented"]["reason"] = "No access request evidence uploaded."
        untestable_rules.append("Request documentation cannot be verified without request log or ticket.")

    # --- Evaluate: Approvals Present ---
    if has_approval_log or has_request_log:
        target_type = "Approval Log" if has_approval_log else "Access Request Log"
        rules["approvals_present"]["status"] = "pass"
        rules["approvals_present"]["reason"] = "Valid approval status found for all logged requests."
        for ftype, df in dataframes:
            if ftype != target_type:
                continue
            cols = [str(c).lower().strip() for c in df.columns]
            status_col_name = next((c for c in cols if "status" in c or "approv" in c or "state" in c), None)
            req_id_col_name = next(
                (c for c in cols if ("request" in c or "ticket" in c or "id" in c) and "emp" not in c and "user" not in c),
                None,
            )

            if status_col_name:
                status_col = df.columns[cols.index(status_col_name)]
                req_id_col = df.columns[cols.index(req_id_col_name)] if req_id_col_name else None

                for _, row in df.iterrows():
                    val = str(row[status_col]).lower().strip()
                    if val in ["no", "false", "f", "missing", "pending", "rejected", "unauthorized", "denied", "none", "nan", ""] or pd.isna(row[status_col]):
                        req_label = str(row[req_id_col]) if req_id_col else f"Row {_}"
                        rules["approvals_present"]["status"] = "fail"
                        rules["approvals_present"]["reason"] = "Exceptions noted: missing or invalid approvals."
                        rules["approvals_present"]["exceptions"].append({
                            "evidence": target_type,
                            "identity": req_label,
                            "detail": f"Status '{val}' indicates approval failure for {req_label}.",
                        })
    elif has_pdf:
        rules["approvals_present"]["status"] = "pass"
        rules["approvals_present"]["reason"] = "PDF approval ticket(s) supplied (assumed passing)."
    else:
        rules["approvals_present"]["status"] = "not_testable"
        rules["approvals_present"]["reason"] = "No approval evidence uploaded."
        untestable_rules.append("Approval completeness cannot be tested without approval evidence.")

    # --- Evaluate: Access Granted Matches Request ---
    if has_any_listing and (has_request_log or has_approval_log):
        rules["access_granted_matches"]["status"] = "pass"
        rules["access_granted_matches"]["reason"] = "Access listing uploaded alongside request evidence. Cross-reference available."
    elif has_any_listing:
        rules["access_granted_matches"]["status"] = "pass"
        rules["access_granted_matches"]["reason"] = "Access listing provided; no request log for deep cross-reference."
    elif has_population:
        rules["access_granted_matches"]["status"] = "pass"
        rules["access_granted_matches"]["reason"] = "User population listing provided as granted access proxy."
    else:
        rules["access_granted_matches"]["status"] = "not_testable"
        rules["access_granted_matches"]["reason"] = "No access listing or population data to verify granted access."
        untestable_rules.append("Granted access verification requires an access listing or user population file.")

    return rules


# =====================================================================
# DEPROVISIONING rules (original JML termination logic, preserved)
# =====================================================================

def _build_deprovisioning_rules(
    files_data, dataframes,
    has_any_approval, has_approval_log,
    has_terminations, has_population,
    has_pdf, missing_evidence, untestable_rules,
):
    rules = {
        "period_matches": {
            "status": "not_testable",
            "reason": "Period coverage cannot be verified from provided headers.",
            "exceptions": [],
        },
        "population_complete": {
            "status": "not_testable" if ("Terminated Users Listing" in missing_evidence or "User Population / HR Data" in missing_evidence) else "pass",
            "reason": (
                "Missing required population data."
                if ("Terminated Users Listing" in missing_evidence or "User Population / HR Data" in missing_evidence)
                else "Population listings appear complete and structured."
            ),
            "exceptions": [],
        },
        "approvals_present": {
            "status": "pass",
            "reason": "Awaiting evaluation.",
            "exceptions": [],
        },
        "timing_sla_met": {
            "status": "pass",
            "reason": "Awaiting evaluation.",
            "exceptions": [],
        },
    }

    exception_found = False
    approval_exception_found = False

    # Evaluate Approvals
    if has_approval_log:
        for ftype, df in dataframes:
            if ftype != "Approval Log":
                continue
            cols = [str(c).lower().strip() for c in df.columns]
            status_col_name = next((c for c in cols if "status" in c or "approv" in c), None)
            req_id_col_name = next(
                (c for c in cols if ("request" in c or "ticket" in c or "id" in c) and "emp" not in c and "user" not in c),
                None,
            )

            if status_col_name:
                status_col = df.columns[cols.index(status_col_name)]
                req_id_col = df.columns[cols.index(req_id_col_name)] if req_id_col_name else None

                for _, row in df.iterrows():
                    val = str(row[status_col]).lower().strip()
                    if val in ["no", "false", "f", "missing", "pending", "rejected", "unauthorized", "none", "nan", ""] or pd.isna(row[status_col]):
                        approval_exception_found = True
                        req_label = str(row[req_id_col]) if req_id_col else "A request"
                        rules["approvals_present"]["exceptions"].append({
                            "evidence": "Approval Log",
                            "identity": req_label,
                            "detail": f"Status '{val}' indicates approval failure.",
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
            if ftype != "Terminations Listing":
                continue
            cols = [str(c).lower().strip() for c in df.columns]
            term_col_name = next((c for c in cols if "term" in c and "date" in c), None)
            acc_col_name = next((c for c in cols if "access" in c and "remov" in c and "date" in c), None)

            if term_col_name and acc_col_name:
                term_col = df.columns[cols.index(term_col_name)]
                acc_col = df.columns[cols.index(acc_col_name)]
                emp_id_col_name = next((c for c in cols if "emp" in c and "id" in c or "user" in c and "id" in c), None)
                emp_id_col = df.columns[cols.index(emp_id_col_name)] if emp_id_col_name else None
                name_col = df.columns[cols.index("name")] if "name" in cols else None

                for _, row in df.iterrows():
                    term_date_raw = row[term_col]
                    access_date_raw = row[acc_col]

                    if pd.isna(term_date_raw) or str(term_date_raw).strip() == "":
                        continue

                    emp_label = ""
                    if emp_id_col:
                        emp_label += str(row[emp_id_col])
                    if name_col:
                        emp_label += f" / {row[name_col]}" if emp_label else str(row[name_col])
                    if not emp_label:
                        emp_label = "An employee"

                    if pd.isna(access_date_raw) or str(access_date_raw).strip() in ["", "nan"]:
                        exception_found = True
                        exc_msg = f"{emp_label} was terminated on {term_date_raw} but access removal is missing (active)."
                        rules["timing_sla_met"]["exceptions"].append({
                            "evidence": "Terminations Listing",
                            "identity": emp_label,
                            "detail": exc_msg,
                        })
                        continue

                    try:
                        term_date = pd.to_datetime(term_date_raw, errors="coerce", utc=True)
                        access_date = pd.to_datetime(access_date_raw, errors="coerce", utc=True)
                        if pd.isna(term_date) or pd.isna(access_date):
                            continue
                        diff = access_date - term_date
                        if diff.total_seconds() > 86400:  # 24 hours
                            exception_found = True
                            exc_msg = f"{emp_label} access removed on {access_date_raw}, exceeding 24h SLA from {term_date_raw}."
                            rules["timing_sla_met"]["exceptions"].append({
                                "evidence": "Terminations Listing",
                                "identity": emp_label,
                                "detail": exc_msg,
                            })
                    except Exception:
                        pass
            else:
                rules["timing_sla_met"]["status"] = "not_testable"
                rules["timing_sla_met"]["reason"] = "Mapped columns insufficient for deep timing calc."
                untestable_rules.append("Timing SLA cannot be calculated accurately due to missing mapped columns.")
    else:
        rules["timing_sla_met"]["status"] = "not_testable"
        rules["timing_sla_met"]["reason"] = "Required termination evidence was not uploaded."
        untestable_rules.append("Timing SLA cannot be tested without termination listing.")

    # --- Relational Check: Terminated Users vs Active Population ("Zombies") ---
    if has_terminations and has_population:
        term_df = next((df for f, df in dataframes if "Terminations" in f), None)
        pop_df = next((df for f, df in dataframes if "Population" in f), None)

        if term_df is not None and pop_df is not None:
            # Standardize column search
            term_cols = [str(c).lower().strip() for c in term_df.columns]
            pop_cols = [str(c).lower().strip() for c in pop_df.columns]

            term_id_col = next((c for c in term_cols if "emp" in c or "user" in c or "id" in c), None)
            pop_id_col = next((c for c in pop_cols if "emp" in c or "user" in c or "id" in c), None)
            pop_status_col = next((c for c in pop_cols if "status" in c or "active" in c or "state" in c), None)

            if term_id_col and pop_id_col and pop_status_col:
                t_id = term_df.columns[term_cols.index(term_id_col)]
                p_id = pop_df.columns[pop_cols.index(pop_id_col)]
                p_stat = pop_df.columns[pop_cols.index(pop_status_col)]

                term_list = term_df[t_id].dropna().astype(str).tolist()
                for _, p_row in pop_df.iterrows():
                    curr_p_id = str(p_row[p_id])
                    curr_p_stat = str(p_row[p_stat]).lower().strip()
                    if curr_p_id in term_list and curr_p_stat in ["active", "yes", "true", "enabled"]:
                        exception_found = True
                        msg = f"CRITICAL: User {curr_p_id} is on the termination list but remains Active/Enabled in the system pop listing."
                        rules["timing_sla_met"]["exceptions"].append({
                            "evidence": "Relational Analysis",
                            "identity": curr_p_id,
                            "detail": msg,
                        })

    if exception_found:
        rules["timing_sla_met"]["status"] = "fail"
        rules["timing_sla_met"]["reason"] = "Leaver SLA or Retained Access exceptions identified."
    elif rules["timing_sla_met"]["status"] == "pass" and has_terminations:
        rules["timing_sla_met"]["reason"] = "No instances exceeding access removal SLA or retained access found."
    elif has_pdf and not has_terminations: # Only PDF termination listing
        rules["timing_sla_met"]["status"] = "unclear"
        rules["timing_sla_met"]["reason"] = "Termination listing is PDF format; automated row-level timing SLA cannot be tested. Manual review required."

    return rules
