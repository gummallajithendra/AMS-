from flask import Flask, render_template, request, redirect, url_for, session, g, flash, jsonify, send_file
import random, threading
import datetime
import json
from io import BytesIO
from werkzeug.utils import secure_filename

import mysql.connector
import os

# Added libs for downloads
import openpyxl
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

app = Flask(__name__)
app.secret_key = "your_secret_key"

# Database Configuration
DB_HOST = "localhost"
DB_USER = "root" 
DB_PASSWORD = "gummallajithendra06@" 
DB_NAME = "project_db"

# ---------------- Database Connection ----------------
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


# ------------------ Helper functions ------------------

def format_app_number(year, num):
    return f"PEC{year}{num:04d}"

# Concurrency lock for safety
sequence_lock = threading.Lock()

def reserve_new_application_number(coordinator_name=None):
    """
    Reserves the next continuous application number for the current year.
    Format: PEC<YYYY><0001> (e.g., PEC20250001)
    """
    conn = mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        conn.start_transaction()
        
        current_year = datetime.datetime.now().year
        
        # 1. Get the current max numeric_part for this year's pattern to be safe
        # We look for applications matching 'PEC<YYYY>%'
        pattern = f"PEC{current_year}%"
        cur.execute("SELECT MAX(numeric_part) as mx FROM applications WHERE application_number LIKE %s", (pattern,))
        row = cur.fetchone()
        
        current_max = 0
        if row and row['mx']:
            current_max = row['mx']
            
        # 2. Determine next number
        new_num = current_max + 1
        
        # 3. Generate new App Number
        application_number = format_app_number(current_year, new_num)
        now = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

        # 4. Insert reserved row
        cur.execute("""
            INSERT INTO applications (application_number, numeric_part, coordinator, status, date_opened)
            VALUES (%s, %s, %s, 'reserved', %s)
        """, (application_number, new_num, coordinator_name or '', now))

        conn.commit()
        return application_number, new_num
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()

def get_next_application_number_preview():
    """
    Returns the next expected application number WITHOUT altering the database.
    Useful for displaying 'Preview' in the form before saving.
    """
    conn = mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        current_year = datetime.datetime.now().year
        pattern = f"PEC{current_year}%"
        cur.execute("SELECT MAX(numeric_part) as mx FROM applications WHERE application_number LIKE %s", (pattern,))
        row = cur.fetchone()
        
        current_max = 0
        if row and row['mx']:
            current_max = row['mx']
            
        new_num = current_max + 1
        return format_app_number(current_year, new_num)
    except Exception as e:
        print(f"DEBUG ERROR in preview: {e}")
        return ""
    finally:
        conn.close()


def finalize_save_application(application_number, student_name, father_name, preferred_branch, form_data=None, coordinator_name=None, form_type='normal'):
    """
    Finalize (save) the application: update reserved row to submitted and add fields.
    If reservation doesn't exist, create a new submitted row.
    """
    new_status = 'confirmed' if form_type == 'confirm' else 'visited'
    db = mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )
    cur = db.cursor(dictionary=True, buffered=True)
    try:
        # Check if application exists
        cur.execute("SELECT id FROM applications WHERE application_number = %s", (application_number,))
        row = cur.fetchone()
        now = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        
        if row:
            # update existing reserved row
            cur.execute("""
                UPDATE applications
                SET student_name=%s, father_name=%s, preferred_branch=%s, status=%s,
                    form_data=%s, date_submitted=%s, coordinator=%s
                WHERE application_number=%s
            """, (
                student_name, father_name, preferred_branch, new_status,
                json.dumps(form_data) if form_data is not None else None,
                now, coordinator_name or '', application_number
            ))
        else:
            # If not found (no reservation), create a new submitted row
            numeric_part = None
            try:
                numeric_part = int(application_number.replace('PEC',''))
            except:
                numeric_part = None
            
            cur.execute("""
                INSERT INTO applications (application_number, numeric_part, student_name, father_name, preferred_branch, status, form_data, date_opened, date_submitted, coordinator)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (application_number, numeric_part, student_name, father_name, preferred_branch, new_status,
                  json.dumps(form_data) if form_data is not None else None, now, now, coordinator_name or ''))
        db.commit()
    except Exception as e:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------- Home ----------------
@app.route('/')
def home():
    return render_template('index.html')


# ---------------- Admin ----------------
@app.route('/admin')
def admin_page():
    return render_template('admin_login.html')


@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        try:
            email = request.form['email'].strip()
            password = request.form['password'].strip()
            db = get_db()
            cursor = db.cursor(dictionary=True)
            cursor.execute("SELECT id, first_name, last_name, email FROM admins WHERE email=%s AND password=%s",
                           (email, password))
            user = cursor.fetchone()
            if user:
                session['admin_id'] = user['id']
                session['admin_name'] = f"{user['first_name']} {user['last_name']}"
                session['admin_email'] = user['email']
                return redirect(url_for('admin_dashboard'))
            else:
                flash("Invalid Admin credentials", "error")
                return redirect(url_for('admin_page')) # Redirect to GET route
        except Exception as e:
            return f"Login Error: {str(e)}", 500
    return render_template('admin_login.html')


@app.route('/admin_dashboard')
def admin_dashboard():
    if 'admin_id' in session:
        try:
            db = get_db()
            cursor = db.cursor(dictionary=True)
            
            # Fetch Admin Details
            cursor.execute("SELECT * FROM admins WHERE id=%s", (session['admin_id'],))
            admin = cursor.fetchone()
            
            # Fetch all coordinators
            cursor.execute("SELECT first_name, last_name, email, phone, work FROM coordinators")
            coordinators = cursor.fetchall() or []

            return render_template(
                'admin_dashboard.html',
                admin=admin,
                coordinators=coordinators
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            return f"Dashboard Error: {str(e)}", 500
    return redirect(url_for('admin_page'))


@app.route('/api/admin/profile', methods=['GET', 'POST'])
def admin_profile_api():
    if 'admin_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    db = get_db()

    if request.method == 'GET':
        cur = db.cursor(dictionary=True)
        cur.execute("""
            SELECT first_name, last_name, email, phone, role, dob,
                   address, city, state, pincode, country, photo
            FROM admins WHERE id=%s
        """, (session['admin_id'],))
        row = cur.fetchone()
        if row:
            if row['dob']:
                row['dob'] = str(row['dob'])
            return jsonify(row)
        return jsonify({"error": "Admin not found"}), 404

    if request.method == 'POST':
        try:
            # Handle multipart/form-data (FormData)
            first_name = request.form.get('first_name')
            last_name = request.form.get('last_name')
            email = request.form.get('email')
            phone = request.form.get('phone')
            role = request.form.get('role')
            dob = request.form.get('dob')
            address = request.form.get('address')
            city = request.form.get('city')
            state = request.form.get('state')
            pincode = request.form.get('pincode')
            country = request.form.get('country')

            # Handle photo upload
            photo_path = None
            if 'photo' in request.files:
                file = request.files['photo']
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    # Prepend timestamp to avoid caching/collisions
                    ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                    filename = f"{ts}_{filename}"
                    save_path = os.path.join(app.root_path, 'static', 'uploads', filename)
                    # Ensure directory exists
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    file.save(save_path)
                    photo_path = f"/static/uploads/{filename}"

            cur = db.cursor()

            # Dynamic query construction based on whether photo is updated
            if photo_path:
                query = """
                    UPDATE admins SET
                        first_name=%s, last_name=%s, email=%s, phone=%s,
                        role=%s, dob=%s, address=%s, city=%s, state=%s,
                        pincode=%s, country=%s, photo=%s
                    WHERE id=%s
                """
                params = (
                    first_name, last_name, email, phone, role, dob,
                    address, city, state, pincode, country, photo_path,
                    session['admin_id']
                )
            else:
                 query = """
                    UPDATE admins SET
                        first_name=%s, last_name=%s, email=%s, phone=%s,
                        role=%s, dob=%s, address=%s, city=%s, state=%s,
                        pincode=%s, country=%s
                    WHERE id=%s
                """
                 params = (
                    first_name, last_name, email, phone, role, dob,
                    address, city, state, pincode, country,
                    session['admin_id']
                )

            cur.execute(query, params)
            db.commit()

            # Update session
            session['admin_name'] = f"{first_name} {last_name}"

            return jsonify({"success": True, "message": "Profile updated successfully", "photo": photo_path})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/admin/change_password', methods=['POST'])
def change_admin_password():
    if 'admin_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    current_pass = data.get('current_password')
    new_pass = data.get('new_password')

    if not current_pass or not new_pass:
        return jsonify({"success": False, "error": "Missing fields"}), 400

    db = get_db()
    cur = db.cursor(dictionary=True)
    
    # Verify current password
    cur.execute("SELECT password FROM admins WHERE id=%s", (session['admin_id'],))
    row = cur.fetchone()
    
    if not row or row['password'] != current_pass:
        return jsonify({"success": False, "error": "Incorrect current password"}), 400

    # Update password
    try:
        cur.execute("UPDATE admins SET password=%s WHERE id=%s", (new_pass, session['admin_id']))
        db.commit()
        return jsonify({"success": True, "message": "Password changed successfully"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/save_admin_work', methods=['POST'])
def save_admin_work():
    if 'admin_id' in session:
        work = request.form['work']
        db = get_db()
        cursor = db.cursor()
        cursor.execute("UPDATE admins SET work=%s WHERE id=%s", (work, session['admin_id']))
        db.commit()
    return redirect(url_for('admin_dashboard'))


# ---------------- Coordinator ----------------
@app.route('/coordinator')
def coordinator_page():
    return render_template('coordinator_login.html')


@app.route('/coordinator_login', methods=['POST'])
def coordinator_login():
    email = request.form['email']
    password = request.form['password']
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT id, first_name, last_name, email FROM coordinators WHERE email=%s AND password=%s",
                   (email, password))
    user = cursor.fetchone()
    if user:
        session['coordinator_id'] = user['id']
        session['coordinator_name'] = f"{user['first_name']} {user['last_name']}"
        session['coordinator_email'] = user['email']
        return redirect(url_for('coordinator_dashboard'))
    flash("Invalid Coordinator credentials", "error")
    return redirect(url_for('coordinator_page'))





@app.route('/coordinator_dashboard')
def coordinator_dashboard():
    if 'coordinator_id' not in session:
        return redirect(url_for('coordinator_page'))

    db = get_db()
    cursor = db.cursor(dictionary=True, buffered=True)
    # Include photo in query
    cursor.execute("""
        SELECT first_name, last_name, email, phone, work, photo
        FROM coordinators WHERE id=%s
    """, (session['coordinator_id'],))
    row = cursor.fetchone()

    if row:
        coordinator_data = {
            "first_name": row['first_name'],
            "last_name": row['last_name'],
            "email": row['email'],
            "phone": row['phone'],
            "work": row['work'],
            "photo": row['photo']
        }
    else:
        coordinator_data = {
            "first_name": "",
            "last_name": "",
            "email": "",
            "phone": "",
            "work": "",
            "photo": None
        }

    return render_template(
        'coordinator_dashboard.html',
        coordinator_data=coordinator_data
    )
# ...existing code...
@app.route('/get_coordinator_applications')
def get_coordinator_applications():
    """
    Return JSON list of applications for the logged-in coordinator.
    """
    if 'coordinator_id' not in session:
        return jsonify({"applications": []}), 200

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT application_number, student_name, father_name, preferred_branch,
                   mobile, address, status, date_submitted, form_data, feedback, next_visit
            FROM applications
            WHERE coordinator = %s AND status IN ('visited', 'confirmed')
        """, (session.get('coordinator_name', ''),))
        rows = cur.fetchall()
        
        apps = []
        for r in rows:
            rd = dict(r)
            # parse form_data JSON if present
            form_json = None
            if rd.get('form_data'):
                try:
                    form_json = json.loads(rd['form_data'])
                except Exception:
                    form_json = None
            apps.append({
                "application_number": rd.get('application_number') or "",
                "student_name": rd.get('student_name') or (form_json.get('student_name') if form_json else "") ,
                "father_name": rd.get('father_name') or (form_json.get('father_name') if form_json else ""),
                "preferred_branch": rd.get('preferred_branch') or (form_json.get('preferred_branch') if form_json else ""),
                "mobile": rd.get('mobile') or (form_json.get('mobile') if form_json else ""),
                "address": rd.get('address') or (form_json.get('address') if form_json else ""),
                "status": rd.get('status'),
                "date_submitted": rd.get('date_submitted'),
                "feedback": rd.get('feedback'),
                "next_visit": rd.get('next_visit')
            })
        return jsonify({"applications": apps}), 200
    except Exception as e:
        return jsonify({"error": str(e), "applications": []}), 500


@app.route('/save_feedback', methods=['POST'])
def save_feedback():
    if 'coordinator_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    app_no = data.get('application_number')
    feedback = data.get('feedback')
    next_visit = data.get('next_visit')

    if not app_no or not feedback:
         return jsonify({"error": "Missing fields"}), 400

    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("UPDATE applications SET feedback=%s, next_visit=%s WHERE application_number=%s", 
                   (feedback, next_visit, app_no))
        db.commit()
        return jsonify({"success": True}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/delete_feedback', methods=['POST'])
def delete_feedback():
    if 'admin_id' not in session and 'coordinator_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    app_no = data.get('application_number')

    if not app_no:
        return jsonify({"error": "Missing application number"}), 400

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        # Also clear feedback from form_data JSON if it exists there
        cur.execute("SELECT form_data FROM applications WHERE application_number=%s", (app_no,))
        row = cur.fetchone()
        
        form_data_str = None
        if row and row.get('form_data'):
            try:
                form_data_dict = json.loads(row['form_data'])
                if isinstance(form_data_dict, dict) and 'feedback' in form_data_dict:
                    form_data_dict['feedback'] = ''
                    form_data_str = json.dumps(form_data_dict)
                else:
                    form_data_str = row['form_data']
            except Exception:
                form_data_str = row['form_data']

        cur = db.cursor()
        cur.execute("UPDATE applications SET feedback = NULL, form_data = %s WHERE application_number=%s", (form_data_str, app_no))
        db.commit()
        return jsonify({"success": True}), 200
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500


@app.route('/api/coordinator/profile', methods=['POST'])
def coordinator_profile_api():
    if 'coordinator_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    db = get_db()
    
    try:
        # Handle multipart/form-data
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        # name is usually combined in frontend but we accept split or specific fields
        # If frontend sends 'name', split it
        name = request.form.get('name')
        if name and not first_name:
             parts = name.strip().split(' ', 1)
             first_name = parts[0]
             last_name = parts[1] if len(parts) > 1 else ''

        phone = request.form.get('phone')
        work = request.form.get('work')
        
        # Handle photo upload
        photo_path = None
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename:
                filename = secure_filename(file.filename)
                ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                filename = f"coord_{ts}_{filename}"
                save_path = os.path.join(app.root_path, 'static', 'uploads', filename)
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                file.save(save_path)
                photo_path = f"/static/uploads/{filename}"

        cur = db.cursor()
        
        if photo_path:
            query = """
                UPDATE coordinators SET 
                    first_name=%s, last_name=%s, phone=%s, work=%s, photo=%s
                WHERE id=%s
            """
            params = (first_name, last_name, phone, work, photo_path, session['coordinator_id'])
        else:
            query = """
                UPDATE coordinators SET 
                    first_name=%s, last_name=%s, phone=%s, work=%s
                WHERE id=%s
            """
            params = (first_name, last_name, phone, work, session['coordinator_id'])
        
        cur.execute(query, params)
        db.commit()
        
        # Update session
        session['coordinator_name'] = f"{first_name} {last_name}"
        
        return jsonify({"success": True, "message": "Profile updated successfully", "photo": photo_path})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/save_coordinator_work', methods=['POST'])
def save_coordinator_work():
    if 'coordinator_id' in session:
        work = request.form['work']
        db = get_db()
        cursor = db.cursor()
        cursor.execute("UPDATE coordinators SET work=%s WHERE id=%s", (work, session['coordinator_id']))
        db.commit()
    return redirect(url_for('coordinator_dashboard'))


# ---------------- Application Form ----------------
@app.route('/upload_temp_photo', methods=['POST'])
def upload_temp_photo():
    """
    Temporary endpoint for the multi-page confirm form to upload images before the final submission.
    Returns the file path.
    """
    if 'coordinator_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    if 'photo' not in request.files:
        return jsonify({"error": "No file part"}), 400
        
    file = request.files['photo']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
        
    if file:
        filename = secure_filename(file.filename)
        ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        rand_str = str(random.randint(1000, 9999))
        filename = f"temp_{ts}_{rand_str}_{filename}"
        save_path = os.path.join(app.root_path, 'static', 'uploads', filename)
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        file.save(save_path)
        
        photo_path = f"/static/uploads/{filename}"
        return jsonify({"success": True, "path": photo_path})

    return jsonify({"error": "Failed to handle file"}), 500


@app.route('/conform_application')
@app.route('/conform_application/<page>')
def conform_application(page='first.html'):
    if 'coordinator_id' not in session:
        flash("Please log in as coordinator to access the form", "error")
        return redirect(url_for('coordinator_page'))
    if not page.endswith('.html'):
        page += '.html'
    return render_template(f'application form/{page}')

@app.route('/save_draft', methods=['POST'])
def save_draft():
    if 'coordinator_id' not in session:
        return jsonify({"error": "Not authorized"}), 401
        
    data = request.get_json()
    application_number = data.get('application_number')
    form_data = data.get('form_data')
    
    if not application_number:
        return jsonify({"success": False, "error": "No application number provided for draft."}), 400
        
    db = get_db()
    cursor = db.cursor(dictionary=True, buffered=True)
    
    try:
        # Check if exists
        cursor.execute("SELECT id FROM applications WHERE application_number = %s", (application_number,))
        if cursor.fetchone():
            cursor.execute("""
                UPDATE applications 
                SET form_data = %s,
                    last_modified = %s
                WHERE application_number = %s
            """, (
                json.dumps(form_data) if form_data else None,
                datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                application_number
            ))
            db.commit()
            return jsonify({"success": True, "message": "Draft saved successfully."})
        else:
            return jsonify({"success": False, "error": "Application not found."}), 404
            
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()

# Add this route after your existing routes
# ...existing code...
@app.route('/save_application', methods=['POST'])
def save_application():
    if 'coordinator_id' not in session:
        return jsonify({"error": "Not authorized"}), 401

    data = request.get_json()
    db = get_db()
    
    # Server-side validation
    # Server-side validation
    # application_number is NOT required for new applications (it will be generated)
    # Extract top level fields or fallback to form_data
    form_data = data.get('form_data') or {}
    student_name = data.get('student_name') or form_data.get('student_name')
    father_name = data.get('father_name') or form_data.get('father_name')
    preferred_branch = data.get('preferred_branch') or form_data.get('preferred_branch')
    mobile = data.get('mobile') or form_data.get('mobile') or form_data.get('father_mobile')
    address = data.get('address') or form_data.get('address') or form_data.get('addr_street')
    
    form_type = data.get('form_type', 'normal')
    missing = []
    
    # Check top-level required fields ONLY for normal forms
    if form_type != 'confirm':
        if not student_name: missing.append('student_name')
        if not father_name: missing.append('father_name')
        if not mobile: missing.append('mobile')
        if not address: missing.append('address')
        
        if isinstance(form_data, dict):
            if not form_data.get('gender'):
                # It's okay if gender is missing from form_data if it's not strictly required by backend logic but ideally it should match frontend.
                # Frontend marks it required.
                missing.append('gender')
    
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    # Generate Application Number if not provided
    if not data.get('application_number'):
        try:
             # Reserve new number
             app_num, _ = reserve_new_application_number(session.get('coordinator_name'))
             data['application_number'] = app_num
        except Exception as e:
             return jsonify({"error": f"Failed to generate application number: {str(e)}"}), 500

    new_status = 'confirmed' if form_type == 'confirm' else 'visited'

    cursor = db.cursor(dictionary=True, buffered=True)

    try:
        # Check if application exists
        cursor.execute("""
            SELECT id FROM applications 
            WHERE application_number = %s
        """, (data['application_number'],))
        exists = cursor.fetchone()

        if exists:
            # Try update with full schema
            cursor.execute("""
                UPDATE applications 
                SET student_name = %s,
                    father_name = %s,
                    preferred_branch = %s,
                    mobile = %s,
                    address = %s,
                    status = %s,
                    form_data = %s,
                    last_modified = %s,
                    date_submitted = COALESCE(date_submitted, %s)
                WHERE application_number = %s
            """, (
                student_name,
                father_name,
                preferred_branch,
                mobile,
                address,
                new_status,
                json.dumps(data.get('form_data')) if data.get('form_data') else None,
                datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), # Update last_modified
                datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), # Set date_submitted if null
                data['application_number']
            ))
        else:
            now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            # Try insert with full schema
            cursor.execute("""
                INSERT INTO applications (
                    application_number,
                    student_name,
                    father_name,
                    preferred_branch,
                    mobile,
                    address,
                    status,
                    coordinator,
                    form_data,
                    date_submitted,
                    last_modified
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                data.get('application_number'),
                student_name,
                father_name,
                preferred_branch,
                mobile,
                address,
                new_status,
                session.get('coordinator_name', ''),
                json.dumps(data.get('form_data')) if data.get('form_data') else None,
                now_str, # date_submitted
                now_str  # last_modified (initially same)
            ))

        db.commit()
        return jsonify({"success": True, "application_number": data['application_number']}), 200

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
# ...existing code...
@app.route('/application_form', methods=['GET', 'POST'])
def application_form():
    if 'coordinator_id' not in session:
        flash("Please log in as coordinator to access the form", "error")
        return redirect(url_for('coordinator_page'))

    db = get_db()
    cursor = db.cursor()

    if request.method == 'POST':
        # On save: finalize the reserved application_number (submitted)
        app_number = request.form.get('application_number')
        student_name = request.form.get('student_name', '').strip()
        father_name = request.form.get('father_name', '').strip()
        preferred_branch = request.form.get('preferred_branch', '').strip()

        if not app_number:
            flash("No application number found. Please reopen the form.", "error")
            return redirect(url_for('application_form'))

        if not student_name or not father_name:
            flash("Please fill all required fields!", "error")
            # Re-render form with values (app_number preserved)
            return render_template('form.html', app_number=app_number, student_name=student_name,
                                   father_name=father_name, preferred_branch=preferred_branch)

        # Optionally gather any additional fields into form_data
        form_data = {
            # add more fields here if your form has them
        }

        try:
            coord_name = session.get('coordinator_name', '')
            finalize_save_application(app_number, student_name, father_name, preferred_branch, form_data=form_data, coordinator_name=coord_name)
        except Exception as e:
            flash(f"Error saving application: {e}", "error")
            return redirect(url_for('application_form'))

        flash(f"Application saved successfully! Application No: {app_number}", "success")
        return render_template('form.html', app_number=app_number, student_name=student_name,
                               father_name=father_name, preferred_branch=preferred_branch)

    # GET: when opening the form
    view_app_number = request.args.get('view')
    if view_app_number:
        # View mode: just render form with this number. Frontend will fetch data.
        return render_template('form.html', app_number=view_app_number, view_mode=True)

    try:
        # PReview next number but do not reserve
        preview_num = get_next_application_number_preview()
        return render_template('form.html', app_number=preview_num, view_mode=False)
    except Exception as e:
        flash(f"Error loading form: {e}", "error")
        return render_template('form.html', app_number="", view_mode=False)


@app.route('/delete_reserved_application', methods=['POST'])
def delete_reserved_application():
    data = request.get_json()
    appnum = data.get('application_number')
    if not appnum:
        return jsonify({'success': False, 'error': 'application_number required'}), 400

    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("DELETE FROM applications WHERE application_number=%s AND status='reserved'", (appnum,))
        db.commit()
        return jsonify({'success': True, 'message': 'Reserved application deleted'}), 200
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500





@app.route('/view_confirm_application')
def view_confirm_application():
    """
    Render a read-only view of the confirm application form for a given app_no.
    If the application has form_data (i.e., it was submitted via the confirm form),
    it renders an in-line HTML page with all 7 pages of data pre-filled.
    Otherwise, it redirects to the normal form viewer.
    """
    if 'coordinator_id' not in session and 'admin_id' not in session:
        return redirect(url_for('coordinator_page'))

    app_no = request.args.get('app_no', '').strip()
    if not app_no:
        return "No application number specified.", 400

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT application_number, student_name, father_name, preferred_branch,
               mobile, address, status, form_data, date_submitted
        FROM applications WHERE application_number = %s
    """, (app_no,))
    row = cur.fetchone()

    if not row:
        return f"Application {app_no} not found.", 404

    # If no form_data or not a confirmed application, redirect to normal form viewer
    if row.get('status') != 'confirmed' or not row.get('form_data'):
        return redirect(url_for('application_form', view=app_no))

    try:
        form_data = json.loads(row['form_data']) if isinstance(row['form_data'], str) else row['form_data']
    except Exception:
        form_data = {}

    return render_template('view_confirm_form.html',
                           app_no=app_no,
                           form_data=form_data,
                           student_name=row.get('student_name', ''),
                           status=row.get('status', ''),
                           date_submitted=row.get('date_submitted', ''))






# ---------------- Search, Edit, Delete APIs ----------------

@app.route('/search_application', methods=['GET'])
def search_application():
    """
    Search by application_number (query param: application_number) and return JSON.
    """
    appnum = request.args.get('application_number', '').strip()
    if not appnum:
        return jsonify({"success": False, "error": "application_number query param required"}), 400

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT *
        FROM applications WHERE application_number = %s
    """, (appnum,))
    row = cur.fetchone()
    if not row:
        return jsonify({"success": True, "found": False, "data": None}), 200

    data = dict(row)
    # Parse form_data JSON if present
    if data.get('form_data'):
        try:
            data['form_data'] = json.loads(data['form_data'])
        except Exception:
            pass
    return jsonify({"success": True, "found": True, "data": data}), 200


@app.route('/edit_application', methods=['POST'])
def edit_application():
    """
    Edit an application. Expects JSON or form data including application_number and fields to update.
    Fields supported: student_name, father_name, preferred_branch, form_data
    """
    data = request.get_json() or request.form
    appnum = data.get('application_number')
    if not appnum:
        return jsonify({"success": False, "error": "application_number required"}), 400

    fields = {}
    if 'student_name' in data:
        fields['student_name'] = data.get('student_name')
    if 'father_name' in data:
        fields['father_name'] = data.get('father_name')
    if 'preferred_branch' in data:
        fields['preferred_branch'] = data.get('preferred_branch')
    if 'form_data' in data:
        # ensure JSON string
        try:
            fields['form_data'] = json.dumps(data.get('form_data')) if not isinstance(data.get('form_data'), str) else data.get('form_data')
        except Exception:
            fields['form_data'] = data.get('form_data')

    if not fields:
        return jsonify({"success": False, "error": "No updatable fields provided"}), 400

    # Build SET clause
    set_clause = ", ".join([f"{k} = %s" for k in fields.keys()])
    params = list(fields.values())
    params.append(datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
    params.append(appnum)

    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(f"UPDATE applications SET {set_clause}, last_modified = %s WHERE application_number = %s", params)
        db.commit()
        return jsonify({"success": True, "message": "Updated"}), 200
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------- New Admin APIs ----------------

@app.route('/api/admin/stats')
def admin_stats():
    if 'admin_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        db = get_db()
        cur = db.cursor(dictionary=True)
        
        # ---- Counters (year-aware, computed after req_year is resolved below) ----
        # Placeholder, will be computed after year parsing
        
        today = datetime.date.today()
        cur_year = today.year

        # ---- Find all years that have data in DB ----
        cur.execute("""
            SELECT DISTINCT YEAR(STR_TO_DATE(date_submitted, %s)) as yr
            FROM applications
            WHERE date_submitted IS NOT NULL AND date_submitted != ''
            ORDER BY yr
        """, ('%Y-%m-%d %H:%i:%s',))
        db_years = sorted(set(
            int(r['yr']) for r in cur.fetchall() if r['yr'] is not None
        ))
        # Include 10 previous years + current + next 3 years for a full scrollable list
        fallback_years = list(range(cur_year - 10, cur_year + 4))
        db_years = sorted(set(db_years + fallback_years))

        # ---- Requested year (start year of academic year, default = current year) ----
        # 'all' means show all-time data (no year filter)
        year_param = request.args.get('year', '')
        show_all_years = (year_param == 'all' or year_param == '')
        if show_all_years:
            req_year = cur_year   # used for monthly chart labels
        else:
            try:
                req_year = int(year_param)
            except (ValueError, TypeError):
                req_year = cur_year
        all_year_labels = [str(y) for y in db_years]   # used for yearly bar chart

        month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

        # ---- Last 7 days labels ----
        weekly_labels = []
        for i in range(6, -1, -1):
            d = today - datetime.timedelta(days=i)
            weekly_labels.append(d.strftime("%a %d/%m"))

        # ---- Helper: weekly counts ----
        def get_weekly(where_clause):
            result = []
            for i in range(6, -1, -1):
                d = today - datetime.timedelta(days=i)
                d_str = d.strftime("%Y-%m-%d")
                cur.execute(f"""
                    SELECT COUNT(*) as c FROM applications
                    WHERE {where_clause}
                      AND DATE(STR_TO_DATE(date_submitted, %s)) = %s
                """, ('%Y-%m-%d %H:%i:%s', d_str))
                row = cur.fetchone()
                result.append(row['c'] if row else 0)
            return result

        # ---- Helper: 12-month counts for a given calendar year ----
        def get_monthly(where_clause, year):
            cur.execute(f"""
                SELECT MONTH(STR_TO_DATE(date_submitted, %s)) as m, COUNT(*) as c
                FROM applications
                WHERE {where_clause}
                  AND YEAR(STR_TO_DATE(date_submitted, %s)) = %s
                GROUP BY m
            """, ('%Y-%m-%d %H:%i:%s', '%Y-%m-%d %H:%i:%s', str(year)))
            mm = {r['m']: r['c'] for r in cur.fetchall() if r['m'] is not None}
            return [mm.get(i+1, 0) for i in range(12)]

        # ---- Helper: count per each known year (for yearly bar) ----
        def get_yearly(where_clause):
            totals = []
            for yr in db_years:
                cur.execute(f"""
                    SELECT COUNT(*) as c FROM applications
                    WHERE {where_clause}
                      AND YEAR(STR_TO_DATE(date_submitted, %s)) = %s
                """, ('%Y-%m-%d %H:%i:%s', str(yr)))
                row = cur.fetchone()
                totals.append(row['c'] if row else 0)
            return totals

        # ---- Helper: dept breakdown, optionally filtered by year ----
        def get_dept(where_clause, year=None):
            if year:
                cur.execute(f"""
                    SELECT preferred_branch, COUNT(*) as c FROM applications
                    WHERE {where_clause}
                      AND YEAR(STR_TO_DATE(date_submitted, %s)) = %s
                    GROUP BY preferred_branch
                """, ('%Y-%m-%d %H:%i:%s', str(year)))
            else:
                cur.execute(f"""
                    SELECT preferred_branch, COUNT(*) as c FROM applications
                    WHERE {where_clause} GROUP BY preferred_branch
                """)
            rows = cur.fetchall()
            return (
                [r['preferred_branch'] for r in rows if r['preferred_branch']],
                [r['c'] for r in rows if r['preferred_branch']]
            )

        # ====== Admissions (confirmed) ======
        adm_w = "status='confirmed'"
        adm_weekly   = get_weekly(adm_w)
        adm_monthly  = get_monthly(adm_w, req_year)   # 12 months of selected year
        adm_yearly   = get_yearly(adm_w)
        adm_dept_l, adm_dept_d = get_dept(adm_w, req_year if not show_all_years else None)

        # ====== Visited = ALL statuses ======
        vis_w = "status IN ('visited','confirmed','pending')"
        vis_weekly   = get_weekly(vis_w)
        vis_monthly  = get_monthly(vis_w, req_year)   # 12 months of selected year
        vis_yearly   = get_yearly(vis_w)
        vis_dept_l, vis_dept_d = get_dept(vis_w, req_year if not show_all_years else None)

        # ====== Year-filtered counters for the counter cards ======
        if show_all_years:
            cur.execute("SELECT COUNT(*) as c FROM applications WHERE status='confirmed'")
            admissions = cur.fetchone()['c']
            cur.execute("SELECT COUNT(*) as c FROM applications WHERE status IN ('visited', 'confirmed', 'pending')")
            enrollments = cur.fetchone()['c']
        else:
            cur.execute("""
                SELECT COUNT(*) as c FROM applications
                WHERE status='confirmed'
                  AND YEAR(STR_TO_DATE(date_submitted, %s)) = %s
            """, ('%Y-%m-%d %H:%i:%s', str(req_year)))
            admissions = cur.fetchone()['c']
            cur.execute("""
                SELECT COUNT(*) as c FROM applications
                WHERE status IN ('visited', 'confirmed', 'pending')
                  AND YEAR(STR_TO_DATE(date_submitted, %s)) = %s
            """, ('%Y-%m-%d %H:%i:%s', str(req_year)))
            enrollments = cur.fetchone()['c']

        return jsonify({
            "counters": {"admissions": admissions, "enrollments": enrollments},
            "meta": {
                "cur_year":  cur_year,
                "req_year":  req_year,
                "all_years": db_years       # list of ints e.g. [2024, 2025, 2026]
            },
            "admissions_charts": {
                "weekly":  {"labels": weekly_labels,   "data": adm_weekly},
                "monthly": {"labels": month_names,     "data": adm_monthly, "year": req_year},
                "yearly":  {"labels": all_year_labels, "data": adm_yearly},
                "dept":    {"labels": adm_dept_l,      "data": adm_dept_d}
            },
            "visited_charts": {
                "weekly":  {"labels": weekly_labels,   "data": vis_weekly},
                "monthly": {"labels": month_names,     "data": vis_monthly, "year": req_year},
                "yearly":  {"labels": all_year_labels, "data": vis_yearly},
                "dept":    {"labels": vis_dept_l,      "data": vis_dept_d}
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/admin/coordinators', methods=['GET', 'POST', 'DELETE'])
def admin_coordinators():
    if 'admin_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    db = get_db()
    
    if request.method == 'GET':
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT id, first_name, last_name, email, phone, work, photo FROM coordinators")
        rows = cur.fetchall()
        result = []

        # Optional year filter from query param: ?year=2025 or ?year=all
        year_param = request.args.get('year', 'all')
        filter_year = None
        if year_param and year_param != 'all':
            try:
                filter_year = int(year_param)
            except (ValueError, TypeError):
                filter_year = None

        for r in rows:
            coord_name = f"{r['first_name']} {r['last_name']}"

            # Admissions count — filtered by year if requested
            if filter_year:
                cur.execute("""
                    SELECT COUNT(*) as c FROM applications
                    WHERE coordinator=%s AND status='confirmed'
                      AND YEAR(STR_TO_DATE(date_submitted, %s)) = %s
                """, (coord_name, '%Y-%m-%d %H:%i:%s', str(filter_year)))
            else:
                cur.execute(
                    "SELECT COUNT(*) as c FROM applications WHERE coordinator=%s AND status='confirmed'",
                    (coord_name,)
                )
            count = cur.fetchone()['c']

            # Recent students (last 5) — filtered by year if requested
            if filter_year:
                cur.execute("""
                    SELECT student_name, application_number FROM applications
                    WHERE coordinator=%s AND status IN ('visited','confirmed')
                      AND YEAR(STR_TO_DATE(date_submitted, %s)) = %s
                    LIMIT 5
                """, (coord_name, '%Y-%m-%d %H:%i:%s', str(filter_year)))
            else:
                cur.execute(
                    "SELECT student_name, application_number FROM applications WHERE coordinator=%s AND status IN ('visited','confirmed') LIMIT 5",
                    (coord_name,)
                )
            students = [{"name": s['student_name'], "appId": s['application_number']} for s in cur.fetchall()]

            photo_url = r['photo'] if r['photo'] else "https://via.placeholder.com/100"

            result.append({
                "id": r['id'],
                "username": coord_name,
                "email": r['email'],
                "photo": photo_url,
                "admissions": count,
                "students": students,
                "year": year_param   # echo back so frontend can display
            })
        return jsonify(result)

    if request.method == 'POST':
        data = request.get_json()
        try:
            cur = db.cursor()
            # Split name safely
            parts = data.get('username', '').split(' ', 1)
            fname = parts[0]
            lname = parts[1] if len(parts) > 1 else ''
            
            cur.execute("INSERT INTO coordinators (first_name, last_name, email, phone, password, work) VALUES (%s, %s, %s, %s, %s, %s)",
                       (fname, lname, data['email'], '0000000000', data['password'], ''))
            db.commit()
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    if request.method == 'DELETE':
        cid = request.args.get('id')
        cur = db.cursor()
        cur.execute("DELETE FROM coordinators WHERE id=%s", (cid,))
        db.commit()
        return jsonify({"success": True})

@app.route('/api/admin/feedback', methods=['GET', 'POST'])
def admin_feedback():
    if 'admin_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    db = get_db()
    
    if request.method == 'GET':
        cur = db.cursor(dictionary=True)
        # Fetching basic application data + columns for feedback
        cur.execute("SELECT * FROM applications WHERE status IN ('visited', 'confirmed')")
        rows = cur.fetchall()
        data = []
        for r in rows:
            form_json = {}
            if r['form_data']:
                try: form_json = json.loads(r['form_data'])
                except: pass
            
            # Prioritize dedicated columns, fallback to form_data or empty
            fb = r.get('feedback')
            if not fb:
                fb = form_json.get('feedback', '')

            nv = r.get('next_visit')
            if not nv:
                nv = form_json.get('next_visit', '')

            data.append({
                "appNo": r['application_number'],
                "student": r['student_name'],
                "coordinator": r['coordinator'],
                "mobile": r['mobile'],
                "address": r['address'],
                "preferred_branch": r['preferred_branch'],
                "feedback": fb, 
                "next_visit": nv
            })
        return jsonify(data)
    
    if request.method == 'POST': 
        return jsonify({"error": "Use /edit_application for updates"}), 400

@app.route('/api/admin/work-log')
def admin_work_log():
    # Return simple work log data
    # Real implementation would need a separate 'logs' table.
    # We will return mock data or query recent applications by date.
    if 'admin_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    
    db = get_db()
    cur = db.cursor(dictionary=True)
    
    today = datetime.date.today().isoformat()
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    
    cur.execute("SELECT coordinator, application_number, student_name, preferred_branch, status FROM applications WHERE DATE(date_submitted) = %s", (today,))
    today_rows = [{"coordinator": r['coordinator'], "appId": r['application_number'], "student": r['student_name'], "branch": r['preferred_branch'], "status": r['status']} for r in cur.fetchall()]
    
    cur.execute("SELECT coordinator, application_number, student_name, preferred_branch, status FROM applications WHERE DATE(date_submitted) = %s", (yesterday,))
    yesterday_rows = [{"coordinator": r['coordinator'], "appId": r['application_number'], "student": r['student_name'], "branch": r['preferred_branch'], "status": r['status']} for r in cur.fetchall()]
    
    return jsonify({"today": today_rows, "yesterday": yesterday_rows})






@app.route("/check_data")
def check_data():
    start = request.args.get("start_date")
    end = request.args.get("end_date")
    
    if not start or not end:
        return jsonify({"error": "Start and end dates required"}), 400

    try:
        db = get_db()
        cur = db.cursor(dictionary=True)
        # count applications submitted in range
        cur.execute("""
            SELECT COUNT(*) as count FROM applications
            WHERE date_submitted BETWEEN %s AND %s
        """, (start + " 00:00:00", end + " 23:59:59"))
        row = cur.fetchone()
        count = row['count'] if row else 0
        return jsonify({"count": count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/download_excel', methods=['GET'])
def download_excel():
    start = request.args.get('start_date')
    end = request.args.get('end_date')
    chart = request.args.get('chart', '0')
    branch = request.args.get('branch', '')
    status = request.args.get('status', '')

    db = get_db()
    cur = db.cursor(dictionary=True)

    query = "SELECT * FROM applications WHERE date_submitted BETWEEN %s AND %s"
    params = [start + " 00:00:00", end + " 23:59:59"]
    if branch:
        query += " AND preferred_branch = %s"
        params.append(branch)
    if status:
        query += " AND status = %s"
        params.append(status)
    cur.execute(query, tuple(params))
    rows = cur.fetchall()

    if not rows:
        return "No data found for the selected dates.", 404

    import openpyxl
    from io import BytesIO
    from openpyxl.chart import PieChart, Reference

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Applications"

    headers = ["Application No", "Student Name", "Father Name", "Mobile", "Address", "Department", "Form Data", "Date Submitted"]
    ws.append(headers)

    dept_count = {}
    for r in rows:
        rdict = dict(r)
        form_json = rdict.get('form_data') or ''
        ws.append([
            rdict.get('application_number'),
            rdict.get('student_name'),
            rdict.get('father_name'),
            rdict.get('mobile'),
            rdict.get('address'),
            rdict.get('preferred_branch'),
            form_json,
            rdict.get('date_submitted')
        ])
        dept = rdict.get('preferred_branch')
        if dept:
            dept_count[dept] = dept_count.get(dept, 0) + 1

    if chart == '1' and dept_count:
        ws_chart = wb.create_sheet(title="Department Pie Chart")
        ws_chart.append(["Department", "Count"])
        for dept, count in dept_count.items():
            ws_chart.append([dept, count])
        pie = PieChart()
        data = Reference(ws_chart, min_col=2, min_row=1, max_row=len(dept_count)+1)
        labels = Reference(ws_chart, min_col=1, min_row=2, max_row=len(dept_count)+1)
        pie.add_data(data, titles_from_data=True)
        pie.set_categories(labels)
        pie.title = "Students by Department"
        ws_chart.add_chart(pie, "E5")

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    from flask import send_file
    return send_file(buf, as_attachment=True, download_name=f"applications_{start}_{end}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route('/download_pdf', methods=['GET'])
def download_pdf():
    start = request.args.get('start_date')
    end = request.args.get('end_date')
    branch = request.args.get('branch', '')
    status = request.args.get('status', '')

    db = get_db()
    cur = db.cursor(dictionary=True)

    query = "SELECT * FROM applications WHERE date_submitted BETWEEN %s AND %s"
    params = [start + " 00:00:00", end + " 23:59:59"]
    if branch:
        query += " AND preferred_branch = %s"
        params.append(branch)
    if status:
        query += " AND status = %s"
        params.append(status)
    cur.execute(query, tuple(params))
    rows = cur.fetchall()

    if not rows:
        return "No data found for the selected dates.", 404

    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    x_margin = 40
    y = height - 50
    line_height = 14

    headers = ["App No", "Student", "Father", "Mobile", "Address", "Dept", "Date Submitted"]
    p.setFont("Helvetica-Bold", 9)
    x_positions = [x_margin + i*70 for i in range(len(headers))]
    for i, h in enumerate(headers):
        p.drawString(x_positions[i], y, h)
    y -= line_height
    p.setFont("Helvetica", 9)

    for r in rows:
        rdict = dict(r)
        rowvals = [
            rdict.get('application_number') or '',
            rdict.get('student_name') or '',
            rdict.get('father_name') or '',
            rdict.get('mobile') or '',
            rdict.get('address') or '',
            rdict.get('preferred_branch') or '',
            rdict.get('date_submitted') or ''
        ]
        for i, val in enumerate(rowvals):
            p.drawString(x_positions[i], y, str(val)[:12])
        y -= line_height
        if y < 60:
            p.showPage()
            y = height - 50
            p.setFont("Helvetica-Bold", 9)
            for i, h in enumerate(headers):
                p.drawString(x_positions[i], y, h)
            y -= line_height
            p.setFont("Helvetica", 9)

    p.save()
    buffer.seek(0)
    from flask import send_file
    return send_file(buffer, as_attachment=True, download_name=f"applications_{start}_{end}.pdf", mimetype="application/pdf")

@app.route('/search_students')
def search_students():
    if 'coordinator_id' not in session:
        return jsonify({"error": "Not authorized"}), 401
        
    search_term = request.args.get('term', '').lower()
    
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT * FROM applications 
            WHERE (LOWER(student_name) LIKE %s OR 
                  LOWER(application_number) LIKE %s) AND
                  coordinator = %s
        """, (f'%{search_term}%', f'%{search_term}%', session.get('coordinator_name', '')))
        
        students = []
        for row in cursor.fetchall():
            students.append({
                'application_number': row['application_number'],
                'student_name': row['student_name'],
                'father_name': row['father_name'],
                'preferred_branch': row['preferred_branch'],
                'mobile': row['mobile'],
                'address': row['address'],
                'status': row.get('status', ''),
                'next_visit': row.get('next_visit', ''),
                'feedback': row.get('feedback', '')
            })
            
        return jsonify({"students": students}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------- Logout ----------------
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))



# ---------------- Database Setup ----------------
def init_db():
    """
    Initialize or upgrade the database schema safely using external script.
    """
    try:
        import create_mysql_schema
        create_mysql_schema.create_schema()
    except Exception as e:
        print(f"Database initialization failed: {e}")

@app.errorhandler(Exception)
def handle_500(e):
    import traceback
    return f"<pre>{traceback.format_exc()}</pre>", 500

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
