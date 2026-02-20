
import requests
import json
import time
import sys

# Configuration
BASE_URL = "http://localhost:5000"
LOGIN_URL = f"{BASE_URL}/coordinator_login"
DASHBOARD_URL = f"{BASE_URL}/coordinator_dashboard"
SAVE_APP_URL = f"{BASE_URL}/save_application"
GET_APPS_URL = f"{BASE_URL}/get_coordinator_applications"

# Test Data
COORDINATOR_EMAIL = "test_coord@example.com" # You might need to adjust this if you don't have this user, or use an existing one
COORDINATOR_PASSWORD = "password123"

# Mock form data
TEST_APP_NUMBER = f"PEC{int(time.time())}"
FORM_DATA = {
    "application_number": TEST_APP_NUMBER,
    "student_name": "Test Student",
    "father_name": "Test Father",
    "preferred_branch": "CSE",
    "mobile": "1234567890",
    "address": "123 Test St",
    "form_data": {
        "gender": "Male",
        "qualification": "12th",
        "grade": "95",
        "extra_field": "Extra Value"
    }
}

def log(msg):
    with open("verify_result.txt", "a") as f:
        f.write(str(msg) + "\n")
    print(msg)

def verify_submission():
    # clear log
    with open("verify_result.txt", "w") as f:
        f.write("Starting verification...\n")

    session = requests.Session()
    
    # 1. Login (assuming we have a coordinator account, otherwise we might need to signup first or manually insert one)
    # For now, let's assume we can hit the endpoint without login if we mock the session or just try to hit save_application
    # But save_application checks for 'coordinator_id' in session.
    # So we need a valid session. 
    
    # Let's try to signup a temp coordinator first to be sure
    MAX_RETRIES = 3
    signup_url = f"{BASE_URL}/coordinator_signup"
    coord_email = f"auto_test_{int(time.time())}@example.com"
    
    log(f"Creating temp coordinator: {coord_email}")
    try:
        session.post(signup_url, data={
            "first_name": "Auto",
            "last_name": "Test",
            "email": coord_email,
            "phone": "9999999999",
            "password": "password"
        })
    except Exception as e:
        log(f"Signup failed (might already allow login): {e}")

    # Login
    log("Logging in...")
    login_resp = session.post(LOGIN_URL, data={
        "email": coord_email,
        "password": "password"
    })
    
    if "coordinator_dashboard" not in login_resp.url and login_resp.status_code != 200:
        log("Login failed. Check server or credentials.")
        # Proceeding might fail but let's try
    
    # 2. Get initial count
    log("Fetching initial count...")
    apps_resp = session.get(GET_APPS_URL)
    initial_count = 0
    try:
        data = apps_resp.json()
        initial_count = len(data.get('applications', []))
        log(f"Initial application count: {initial_count}")
    except Exception as e:
        log(f"Failed to get apps: {e}")

    # 3. Submit Form
    log(f"Submitting application {TEST_APP_NUMBER}...")
    save_resp = session.post(SAVE_APP_URL, json=FORM_DATA)
    log(f"Save response: {save_resp.status_code} - {save_resp.text}")
    
    if save_resp.status_code != 200:
        log("Save failed!")
        return

    # 4. Verify Count Increase
    log("Verifying count increase...")
    apps_resp = session.get(GET_APPS_URL)
    try:
        data = apps_resp.json()
        new_count = len(data.get('applications', []))
        log(f"New application count: {new_count}")
        
        if new_count == initial_count + 1:
            log("SUCCESS: Student count increased by 1.")
        else:
            log("FAILURE: Student count did not increase as expected.")
            
        # Verify data integrity
        submitted_app = next((a for a in data.get('applications') if a['application_number'] == TEST_APP_NUMBER), None)
        if submitted_app:
            log(f"Found submitted app: {submitted_app['student_name']}")
            # Ideally verify form_data too, but get_coordinator_applications might not return the full JSON blob unless we check carefully
        else:
            log("FAILURE: Could not find the submitted application in the list.")

    except Exception as e:
        log(f"Failed to verify: {e}")

def verify_missing_fields():
    log("\nRunning Missing Fields Test...")
    session = requests.Session()
    
    # Login first
    coord_email = "test_coord@example.com" # reusing existing or temp one if possible
    # We need a new login or reuse existing if script runs sequentially.
    # Let's just create another temp one or use the one from previous run if we return it? 
    # To keep it simple, I'll just do a fresh login with a new temp user.
    
    signup_url = f"{BASE_URL}/coordinator_signup"
    auth_email = f"neg_test_{int(time.time())}@example.com"
    try:
        session.post(signup_url, data={"first_name":"Neg","last_name":"Test","email":auth_email,"phone":"8888888888","password":"pass"})
        session.post(LOGIN_URL, data={"email":auth_email,"password":"pass"})
    except:
        pass

    # Missing student_name
    BAD_DATA = FORM_DATA.copy()
    BAD_DATA['application_number'] = f"PEC{int(time.time())}_bad"
    BAD_DATA['student_name'] = "" # Empty
    
    resp = session.post(SAVE_APP_URL, json=BAD_DATA)
    log(f"Missing field response: {resp.status_code} - {resp.text}")
    
    if resp.status_code == 400 and "Missing required fields" in resp.text:
        log("SUCCESS: Server rejected application with missing fields.")
    else:
        log("FAILURE: Server accepted application with missing fields or gave wrong error.")

if __name__ == "__main__":
    try:
        verify_submission()
        verify_missing_fields()
    except Exception as e:
        log(f"An error occurred: {e}")
