import pandas as pd
from analysis import analyze_evidence

df_users = pd.DataFrame({
    "employee_id": ["EMP005"],
    "name": ["Charlie Wilson"],
    "termination_date": ["2024-12-15"],
    "access_removed_date": ["2024-12-20"]
})

df_users.to_csv("test_charlie.csv", index=False)

# Mock empty PDF so we satisfy has_pdf
with open("test_approval.pdf", "w") as f:
    f.write("%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\nxref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000122 00000 n \ntrailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n210\n%%EOF\n")

print("--- Calling analyze_evidence ---")
try:
    result = analyze_evidence(1, {}, ["test_charlie.csv", "test_approval.pdf"])
    import json
    print(json.dumps(result, indent=2))
except Exception as e:
    print("Error:", e)
