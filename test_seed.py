import requests

BASE_URL = "http://127.0.0.1:8002"

# 1. Create Control
control_data = {
    "description": "User access to Finance System granted based on approved requests. Leavers disabled within 3 business days.",
    "test_procedure": "Obtain user listing 2024-12-31. Sample 25 joiners/leavers. Verify approvals and timing."
}
r_control = requests.post(f"{BASE_URL}/api/controls/", data=control_data)
control = r_control.json()
control_id = control["id"]
print(f"Created Control ID {control_id}")

# 2. Generate Sample Files
r_sample = requests.post(f"{BASE_URL}/api/dev/generate_sample")
print(f"Generated samples: {r_sample.status_code}")

# 3. Create Test Run with files
files = [
    ('files', ('sample_users.csv', open('uploads/sample_users.csv', 'rb'), 'text/csv')),
    ('files', ('sample_hr_leavers.csv', open('uploads/sample_hr_leavers.csv', 'rb'), 'text/csv')),
    ('files', ('sample_approval.pdf', open('uploads/sample_approval.pdf', 'rb'), 'application/pdf'))
]
r_run = requests.post(f"{BASE_URL}/api/test_runs/", data={'control_id': control_id}, files=files)
run = r_run.json()
print(f"Created Test Run ID {run['id']}")

