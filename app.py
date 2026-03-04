from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import check_password_hash, generate_password_hash

from db import init_db, get_conn
from auth import login_required, admin_required

app = Flask(__name__)
app.config.from_pyfile("config.py", silent=True)
app.secret_key = app.config.get("SECRET_KEY", "change-this-secret")

# Create DB + tables + default admin
init_db()

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username=? AND is_active=1", (username,))
        user = cur.fetchone()
        conn.close()

        if not user or not check_password_hash(user["password_hash"], password):
            flash("Invalid username or password.", "danger")
            return redirect(url_for("login"))

        session["user_id"] = user["id"]
        session["role"] = user["role"]
        session["full_name"] = user["full_name"]
        session["username"] = user["username"]

        flash("Login successful.", "success")
        return redirect(url_for("dashboard"))

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("login"))

@app.route("/")
@login_required
def dashboard():
    today = str(date.today())

    conn = get_conn()
    cur = conn.cursor()

    # Total active students
    cur.execute("SELECT COUNT(*) AS cnt FROM students WHERE is_active=1")
    total_students = cur.fetchone()["cnt"]

    # Today's attendance (overall)
    cur.execute("""
        SELECT
          SUM(CASE WHEN status='P' THEN 1 ELSE 0 END) AS present,
          SUM(CASE WHEN status='A' THEN 1 ELSE 0 END) AS absent,
          COUNT(*) AS marked
        FROM attendance
        WHERE att_date=?
    """, (today,))
    row = cur.fetchone()
    present = row["present"] or 0
    absent = row["absent"] or 0
    marked = row["marked"] or 0

    # Not marked students = total - marked rows
    not_marked = max(total_students - marked, 0)

    # Attendance % (based on marked or total? We'll use total_students for simple view)
    percentage = 0
    if total_students > 0:
        percentage = round((present / total_students) * 100, 1)

    # Batch-wise summary for today
    # We count present/absent among students assigned to that batch.
    cur.execute("""
        SELECT
          b.id AS batch_id,
          c.course_name,
          b.batch_name,
          COUNT(sb.student_id) AS batch_students,
          SUM(CASE WHEN a.status='P' THEN 1 ELSE 0 END) AS present,
          SUM(CASE WHEN a.status='A' THEN 1 ELSE 0 END) AS absent
        FROM batches b
        JOIN courses c ON c.id=b.course_id
        LEFT JOIN student_batches sb ON sb.batch_id=b.id
        LEFT JOIN attendance a
          ON a.student_id = sb.student_id AND a.att_date=?
        WHERE b.is_active=1
        GROUP BY b.id
        ORDER BY c.course_name, b.batch_name
    """, (today,))
    batch_rows = cur.fetchall()

    # Add batch % in python
    batches = []
    for r in batch_rows:
        bs = r["batch_students"] or 0
        bp = r["present"] or 0
        ba = r["absent"] or 0
        bmarked = bp + ba
        bnot = max(bs - bmarked, 0)
        bperc = round((bp / bs) * 100, 1) if bs > 0 else 0
        batches.append({
            "batch_id": r["batch_id"],
            "course_name": r["course_name"],
            "batch_name": r["batch_name"],
            "batch_students": bs,
            "present": bp,
            "absent": ba,
            "not_marked": bnot,
            "percentage": bperc
        })

        # -----------------------------
    # Students below 75% (overall)
    # -----------------------------
    cur.execute("""
        SELECT
            s.id,
            s.registration_number,
            s.full_name,
            COALESCE(SUM(CASE WHEN a.status='P' THEN 1 ELSE 0 END), 0) AS present_days,
            COUNT(a.student_id) AS marked_days
        FROM students s
        LEFT JOIN attendance a ON a.student_id = s.id
        WHERE s.is_active=1
        GROUP BY s.id
        HAVING marked_days > 0
           AND (present_days * 100.0 / marked_days) < 75
        ORDER BY (present_days * 100.0 / marked_days) ASC, marked_days DESC
        LIMIT 50
    """)
    low_rows = cur.fetchall()

    low_attendance_students = []
    for r in low_rows:
        percent = round((r["present_days"] * 100.0 / r["marked_days"]), 1) if r["marked_days"] else 0
        low_attendance_students.append({
            "id": r["id"],
            "registration_number": r["registration_number"],
            "full_name": r["full_name"],
            "present_days": r["present_days"],
            "marked_days": r["marked_days"],
            "percent": percent
        })

    conn.close()

    return render_template(
        "dashboard.html",
        today=today,
        total_students=total_students,
        present=present,
        absent=absent,
        not_marked=not_marked,
        percentage=percentage,
        batches=batches,
        low_attendance_students=low_attendance_students
    )

# ---------------- ADMIN: USERS ----------------
@app.route("/users")
@admin_required
def users_list():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, full_name, username, role, is_active, created_at FROM users ORDER BY id DESC")
    users = cur.fetchall()
    conn.close()
    return render_template("users.html", users=users)

@app.route("/users/add", methods=["GET", "POST"])
@admin_required
def user_add():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip()
        role = request.form.get("role", "staff").strip()
        is_active = int(request.form.get("is_active", "1"))
        password = request.form.get("password", "").strip()

        if not full_name or not username or not password:
            flash("Full name, username, and password are required.", "danger")
            return redirect(url_for("user_add"))

        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO users (full_name, username, password_hash, role, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
            """, (full_name, username, generate_password_hash(password), role, is_active))
            conn.commit()
            flash("User created successfully.", "success")
        except Exception:
            flash("Username already exists.", "danger")
        finally:
            conn.close()

        return redirect(url_for("users_list"))

    return render_template("user_form.html", user=None)

@app.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def user_edit(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id=?", (user_id,))
    user = cur.fetchone()

    if not user:
        conn.close()
        flash("User not found.", "danger")
        return redirect(url_for("users_list"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        role = request.form.get("role", "staff").strip()
        is_active = int(request.form.get("is_active", "1"))
        password = request.form.get("password", "").strip()

        if password:
            cur.execute("""
                UPDATE users
                SET full_name=?, role=?, is_active=?, password_hash=?
                WHERE id=?
            """, (full_name, role, is_active, generate_password_hash(password), user_id))
        else:
            cur.execute("""
                UPDATE users
                SET full_name=?, role=?, is_active=?
                WHERE id=?
            """, (full_name, role, is_active, user_id))

        conn.commit()
        conn.close()
        flash("User updated.", "success")
        return redirect(url_for("users_list"))

    conn.close()
    return render_template("user_form.html", user=user)

@app.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def user_delete(user_id):
    # Safety: prevent deleting yourself
    if session.get("user_id") == user_id:
        flash("You cannot delete your own account while logged in.", "danger")
        return redirect(url_for("users_list"))

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    flash("User deleted.", "success")
    return redirect(url_for("users_list"))

# -------- COURSES (Admin) --------

@app.route("/courses")
@admin_required
def courses():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM courses WHERE is_active=1 ORDER BY id DESC")
    courses = cur.fetchall()
    conn.close()
    return render_template("courses.html", courses=courses)

@app.route("/courses/add", methods=["POST"])
@admin_required
def course_add():
    course_name = request.form.get("course_name", "").strip()

    if not course_name:
        flash("Course name required", "danger")
        return redirect(url_for("courses"))

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO courses (course_name) VALUES (?)", (course_name,))
        conn.commit()
        flash("Course added successfully", "success")
    except Exception:
        flash("Course already exists", "danger")
    finally:
        conn.close()

    return redirect(url_for("courses"))

@app.route("/courses/<int:course_id>/edit", methods=["GET", "POST"])
@admin_required
def course_edit(course_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM courses WHERE id=?", (course_id,))
    course = cur.fetchone()

    if not course:
        conn.close()
        flash("Course not found", "danger")
        return redirect(url_for("courses"))

    if request.method == "POST":
        new_name = request.form.get("course_name", "").strip()

        if not new_name:
            flash("Course name required", "danger")
            return redirect(url_for("course_edit", course_id=course_id))

        try:
            cur.execute("UPDATE courses SET course_name=? WHERE id=?", (new_name, course_id))
            conn.commit()
            flash("Course updated successfully", "success")
        except Exception:
            flash("Course name already exists", "danger")
        finally:
            conn.close()

        return redirect(url_for("courses"))

    conn.close()
    return render_template("course_form.html", course=course)

@app.route("/courses/<int:course_id>/delete", methods=["POST"])
@admin_required
def course_delete(course_id):
    conn = get_conn()
    cur = conn.cursor()

    # Safety: If batches exist using this course, block delete (better than breaking)
    cur.execute("SELECT COUNT(*) AS cnt FROM batches WHERE course_id=?", (course_id,))
    cnt = cur.fetchone()["cnt"]

    if cnt > 0:
        conn.close()
        flash("Cannot delete: This course has batches. Delete batches first.", "danger")
        return redirect(url_for("courses"))

    cur.execute("DELETE FROM courses WHERE id=?", (course_id,))
    conn.commit()
    conn.close()

    flash("Course deleted.", "success")
    return redirect(url_for("courses"))

# -------- BATCHES (Admin) --------

@app.route("/batches")
@admin_required
def batches():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id, course_name FROM courses WHERE is_active=1 ORDER BY course_name")
    courses = cur.fetchall()

    cur.execute("""
        SELECT b.*, c.course_name
        FROM batches b
        JOIN courses c ON c.id = b.course_id
        WHERE b.is_active=1
        ORDER BY b.id DESC
    """)
    batches = cur.fetchall()

    conn.close()
    return render_template("batches.html", courses=courses, batches=batches)

@app.route("/batches/add", methods=["POST"])
@admin_required
def batch_add():
    batch_name = request.form.get("batch_name", "").strip()
    course_id = request.form.get("course_id", "").strip()
    timing = request.form.get("timing", "").strip()
    start_date = request.form.get("start_date", "").strip()
    end_date = request.form.get("end_date", "").strip()

    if not batch_name or not course_id:
        flash("Batch name and course are required.", "danger")
        return redirect(url_for("batches"))

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO batches (batch_name, course_id, timing, start_date, end_date)
            VALUES (?, ?, ?, ?, ?)
        """, (batch_name, int(course_id), timing, start_date, end_date))
        conn.commit()
        flash("Batch added successfully.", "success")
    except Exception:
        flash("Batch already exists for this course.", "danger")
    finally:
        conn.close()

    return redirect(url_for("batches"))

@app.route("/batches/<int:batch_id>/edit", methods=["GET", "POST"])
@admin_required
def batch_edit(batch_id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id, course_name FROM courses WHERE is_active=1 ORDER BY course_name")
    courses = cur.fetchall()

    cur.execute("SELECT * FROM batches WHERE id=?", (batch_id,))
    batch = cur.fetchone()

    if not batch:
        conn.close()
        flash("Batch not found.", "danger")
        return redirect(url_for("batches"))

    if request.method == "POST":
        batch_name = request.form.get("batch_name", "").strip()
        course_id = request.form.get("course_id", "").strip()
        timing = request.form.get("timing", "").strip()
        start_date = request.form.get("start_date", "").strip()
        end_date = request.form.get("end_date", "").strip()

        if not batch_name or not course_id:
            flash("Batch name and course are required.", "danger")
            return redirect(url_for("batch_edit", batch_id=batch_id))

        try:
            cur.execute("""
                UPDATE batches
                SET batch_name=?, course_id=?, timing=?, start_date=?, end_date=?
                WHERE id=?
            """, (batch_name, int(course_id), timing, start_date, end_date, batch_id))
            conn.commit()
            flash("Batch updated successfully.", "success")
        except Exception:
            flash("Batch already exists for this course.", "danger")
        finally:
            conn.close()

        return redirect(url_for("batches"))

    conn.close()
    return render_template("batch_form.html", batch=batch, courses=courses)

@app.route("/batches/<int:batch_id>/delete", methods=["POST"])
@admin_required
def batch_delete(batch_id):
    conn = get_conn()
    cur = conn.cursor()

    # Safety: if students already assigned to this batch, block delete
    cur.execute("SELECT COUNT(*) AS cnt FROM student_batches WHERE batch_id=?", (batch_id,))
    cnt = cur.fetchone()["cnt"]
    if cnt > 0:
        conn.close()
        flash("Cannot delete: Students are assigned to this batch. Remove students first.", "danger")
        return redirect(url_for("batches"))

    cur.execute("DELETE FROM batches WHERE id=?", (batch_id,))
    conn.commit()
    conn.close()

    flash("Batch deleted.", "success")
    return redirect(url_for("batches"))

# -------- STUDENTS (Admin) --------

@app.route("/students")
@admin_required
def students():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.*, c.course_name
        FROM students s
        LEFT JOIN courses c ON c.id = s.course_id
        WHERE s.is_active=1
        ORDER BY s.id DESC
    """)
    students = cur.fetchall()
    conn.close()
    return render_template("students.html", students=students)

@app.route("/students/add", methods=["GET", "POST"])
@admin_required
def student_add():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, course_name FROM courses WHERE is_active=1 ORDER BY course_name")
    courses = cur.fetchall()

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        mobile_number = request.form.get("mobile_number", "").strip()
        registration_number = request.form.get("registration_number", "").strip()
        course_id = request.form.get("course_id", "").strip()
        address = request.form.get("address", "").strip()
        qualification = request.form.get("qualification", "").strip()
        date_of_joining = request.form.get("date_of_joining", "").strip()

        if not full_name or not registration_number or not date_of_joining:
            flash("Name, Registration Number, and Date of Joining are required.", "danger")
            conn.close()
            return redirect(url_for("student_add"))

        try:
            cur.execute("""
                INSERT INTO students
                (full_name, mobile_number, registration_number, course_id, address, qualification, date_of_joining)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                full_name,
                mobile_number,
                registration_number,
                int(course_id) if course_id else None,
                address,
                qualification,
                date_of_joining
            ))
            conn.commit()
            flash("Student added successfully.", "success")
            conn.close()
            return redirect(url_for("students"))
        except Exception:
            flash("Registration Number already exists.", "danger")
            conn.close()
            return redirect(url_for("student_add"))

    conn.close()
    return render_template("student_form.html", student=None, courses=courses)

@app.route("/students/<int:student_id>/edit", methods=["GET", "POST"])
@admin_required
def student_edit(student_id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id, course_name FROM courses WHERE is_active=1 ORDER BY course_name")
    courses = cur.fetchall()

    cur.execute("SELECT * FROM students WHERE id=?", (student_id,))
    student = cur.fetchone()

    if not student:
        conn.close()
        flash("Student not found.", "danger")
        return redirect(url_for("students"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        mobile_number = request.form.get("mobile_number", "").strip()
        course_id = request.form.get("course_id", "").strip()
        address = request.form.get("address", "").strip()
        qualification = request.form.get("qualification", "").strip()
        date_of_joining = request.form.get("date_of_joining", "").strip()

        if not full_name or not date_of_joining:
            flash("Name and Date of Joining are required.", "danger")
            conn.close()
            return redirect(url_for("student_edit", student_id=student_id))

        cur.execute("""
            UPDATE students
            SET full_name=?, mobile_number=?, course_id=?, address=?, qualification=?, date_of_joining=?
            WHERE id=?
        """, (
            full_name,
            mobile_number,
            int(course_id) if course_id else None,
            address,
            qualification,
            date_of_joining,
            student_id
        ))
        conn.commit()
        conn.close()
        flash("Student updated.", "success")
        return redirect(url_for("students"))

    conn.close()
    return render_template("student_form.html", student=student, courses=courses)

@app.route("/students/inactive")
@login_required
def inactive_students():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, registration_number, full_name, mobile_number, date_of_joining
        FROM students
        WHERE is_active=0
        ORDER BY full_name
    """)
    students = cur.fetchall()

    conn.close()
    return render_template("students_inactive.html", students=students)


@app.route("/students/deactivate/<int:student_id>", methods=["POST"])
@login_required
def deactivate_student(student_id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("UPDATE students SET is_active=0 WHERE id=?", (student_id,))
    conn.commit()
    conn.close()

    flash("Student deactivated successfully.", "success")
    return redirect(url_for("students"))

@app.route("/students/reactivate/<int:student_id>", methods=["POST"])
@login_required
def reactivate_student(student_id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("UPDATE students SET is_active=1 WHERE id=?", (student_id,))
    conn.commit()
    conn.close()

    flash("Student reactivated successfully.", "success")
    return redirect(url_for("inactive_students"))

@app.route("/students/<int:student_id>/delete", methods=["POST"])
@admin_required
def student_delete(student_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM students WHERE id=?", (student_id,))
    conn.commit()
    conn.close()
    flash("Student deleted.", "success")
    return redirect(url_for("students"))

@app.route("/students/<int:student_id>")
@login_required
def student_profile(student_id):
    conn = get_conn()
    cur = conn.cursor()

    # Student details
    cur.execute("""
        SELECT s.*
             , c.course_name
        FROM students s
        LEFT JOIN courses c ON c.id = s.course_id
        WHERE s.id=?
    """, (student_id,))
    student = cur.fetchone()

    if not student:
        conn.close()
        flash("Student not found.", "danger")
        return redirect(url_for("students"))

    # Batches assigned to student
    cur.execute("""
        SELECT b.id, b.batch_name, c.course_name, b.timing
        FROM student_batches sb
        JOIN batches b ON b.id = sb.batch_id
        JOIN courses c ON c.id = b.course_id
        WHERE sb.student_id=?
        ORDER BY c.course_name, b.batch_name
    """, (student_id,))
    batches = cur.fetchall()

    # Attendance overall summary
    cur.execute("""
        SELECT
          SUM(CASE WHEN status='P' THEN 1 ELSE 0 END) AS present,
          SUM(CASE WHEN status='A' THEN 1 ELSE 0 END) AS absent,
          COUNT(*) AS marked
        FROM attendance
        WHERE student_id=?
    """, (student_id,))
    overall = cur.fetchone()
    overall_present = overall["present"] or 0
    overall_absent = overall["absent"] or 0
    overall_marked = overall["marked"] or 0
    overall_percent = round((overall_present / overall_marked) * 100, 1) if overall_marked > 0 else 0

    # Current month summary
    month = str(date.today())[:7]  # YYYY-MM
    cur.execute("""
        SELECT
          SUM(CASE WHEN status='P' THEN 1 ELSE 0 END) AS present,
          SUM(CASE WHEN status='A' THEN 1 ELSE 0 END) AS absent,
          COUNT(*) AS marked
        FROM attendance
        WHERE student_id=? AND substr(att_date,1,7)=?
    """, (student_id, month))
    m = cur.fetchone()
    month_present = m["present"] or 0
    month_absent = m["absent"] or 0
    month_marked = m["marked"] or 0
    month_percent = round((month_present / month_marked) * 100, 1) if month_marked > 0 else 0

    # Recent attendance (last 10)
    cur.execute("""
        SELECT att_date, status
        FROM attendance
        WHERE student_id=?
        ORDER BY att_date DESC
        LIMIT 10
    """, (student_id,))
    recent = cur.fetchall()

    conn.close()

    return render_template(
        "student_profile.html",
        student=student,
        batches=batches,
        overall_present=overall_present,
        overall_absent=overall_absent,
        overall_marked=overall_marked,
        overall_percent=overall_percent,
        month=month,
        month_present=month_present,
        month_absent=month_absent,
        month_marked=month_marked,
        month_percent=month_percent,
        recent=recent
    )

# -------- STUDENT BATCHES (Admin) --------

@app.route("/students/<int:student_id>/batches", methods=["GET", "POST"])
@admin_required
def student_batches(student_id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM students WHERE id=?", (student_id,))
    student = cur.fetchone()
    if not student:
        conn.close()
        flash("Student not found.", "danger")
        return redirect(url_for("students"))

    cur.execute("""
        SELECT b.id, b.batch_name, b.timing, c.course_name
        FROM batches b
        JOIN courses c ON c.id=b.course_id
        WHERE b.is_active=1
        ORDER BY c.course_name, b.batch_name
    """)
    batches = cur.fetchall()

    cur.execute("SELECT batch_id FROM student_batches WHERE student_id=?", (student_id,))
    assigned_ids = {row["batch_id"] for row in cur.fetchall()}

    if request.method == "POST":
        selected = request.form.getlist("batch_ids")  # multiple

        # Clear old
        cur.execute("DELETE FROM student_batches WHERE student_id=?", (student_id,))

        # Insert new
        for bid in selected:
            cur.execute("""
                INSERT OR IGNORE INTO student_batches (student_id, batch_id, assigned_on)
                VALUES (?, ?, datetime('now'))
            """, (student_id, int(bid)))

        conn.commit()
        conn.close()
        flash("Batches updated.", "success")
        return redirect(url_for("students"))

    conn.close()
    return render_template(
        "student_batches.html",
        student=student,
        batches=batches,
        assigned_ids=assigned_ids
    )

from datetime import date

# -------- ATTENDANCE --------

@app.route("/mark", methods=["GET", "POST"])
@login_required
def mark_attendance():

    batch_id = request.args.get("batch_id")
    att_date = request.args.get("date") or str(date.today())

    conn = get_conn()
    cur = conn.cursor()

    # Load batches for dropdown
    cur.execute("""
        SELECT b.id, b.batch_name, c.course_name
        FROM batches b
        JOIN courses c ON c.id=b.course_id
        WHERE b.is_active=1
        ORDER BY c.course_name, b.batch_name
    """)
    batches = cur.fetchall()

    students = []
    existing = {}

    # -----------------------------
    # LOAD STUDENTS
    # -----------------------------
    if batch_id:

        # Students from selected batch
        cur.execute("""
            SELECT s.id, s.full_name, s.registration_number
            FROM students s
            JOIN student_batches sb ON sb.student_id=s.id
            WHERE sb.batch_id=? AND s.is_active=1
            ORDER BY s.full_name
        """, (batch_id,))
        students = cur.fetchall()

    else:

        # All active students
        cur.execute("""
            SELECT id, full_name, registration_number
            FROM students
            WHERE is_active=1
            ORDER BY full_name
        """)
        students = cur.fetchall()

    # -----------------------------
    # EXISTING ATTENDANCE
    # -----------------------------
    cur.execute("""
        SELECT student_id, status
        FROM attendance
        WHERE att_date=?
    """, (att_date,))
    existing = {row["student_id"]: row["status"] for row in cur.fetchall()}

    # -----------------------------
    # SAVE ATTENDANCE
    # -----------------------------
    if request.method == "POST":

        batch_id = request.form.get("batch_id")
        att_date = request.form.get("att_date")
        present_ids = set(request.form.getlist("present_ids"))
        marked_by = session.get("user_id")

        if batch_id:

            # batch students
            cur.execute("""
                SELECT s.id
                FROM students s
                JOIN student_batches sb ON sb.student_id=s.id
                WHERE sb.batch_id=? AND s.is_active=1
            """, (batch_id,))
            batch_students = cur.fetchall()

        else:

            # all students
            cur.execute("""
                SELECT id
                FROM students
                WHERE is_active=1
            """)
            batch_students = cur.fetchall()

        for s in batch_students:

            sid = str(s["id"])
            status = "P" if sid in present_ids else "A"

            cur.execute("""
                INSERT INTO attendance (student_id, att_date, status, marked_by, marked_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(student_id, att_date)
                DO UPDATE SET
                    status=excluded.status,
                    marked_by=excluded.marked_by,
                    marked_at=excluded.marked_at
            """, (int(sid), att_date, status, marked_by))

        conn.commit()
        conn.close()

        flash("Attendance saved successfully.", "success")

        # Open report
        if request.form.get("go_report") == "1":
            return redirect(url_for("report_daily", date=att_date, batch_id=batch_id))

        return redirect(url_for("mark_attendance", batch_id=batch_id, date=att_date))

    conn.close()

    return render_template(
        "mark_attendance.html",
        batches=batches,
        batch_id=batch_id,
        students=students,
        att_date=att_date,
        existing=existing
    )

@app.route("/audit", methods=["GET"])
@login_required
def audit_log():
    att_date = request.args.get("date") or str(date.today())
    batch_id = request.args.get("batch_id") or ""

    conn = get_conn()
    cur = conn.cursor()

    # Load batches for filter dropdown
    cur.execute("""
        SELECT b.id, b.batch_name, c.course_name
        FROM batches b
        JOIN courses c ON c.id=b.course_id
        WHERE b.is_active=1
        ORDER BY c.course_name, b.batch_name
    """)
    batches = cur.fetchall()

    # Audit rows
    # If batch selected, only students from that batch are considered.
    if batch_id:
        cur.execute("""
            SELECT
                ? AS att_date,
                b.id AS batch_id,
                c.course_name,
                b.batch_name,
                COUNT(a.student_id) AS marked,
                SUM(CASE WHEN a.status='P' THEN 1 ELSE 0 END) AS present,
                SUM(CASE WHEN a.status='A' THEN 1 ELSE 0 END) AS absent,
                u.full_name AS marked_by_name,
                MAX(a.marked_at) AS last_marked_at
            FROM attendance a
            JOIN student_batches sb ON sb.student_id = a.student_id
            JOIN batches b ON b.id = sb.batch_id
            JOIN courses c ON c.id = b.course_id
            LEFT JOIN users u ON u.id = a.marked_by
            WHERE a.att_date=? AND b.id=?
            GROUP BY b.id, a.marked_by
            ORDER BY last_marked_at DESC
        """, (att_date, att_date, batch_id))
        rows = cur.fetchall()
    else:
        # Overall audit (all students marked on that date) grouped by user
        cur.execute("""
            SELECT
                ? AS att_date,
                NULL AS batch_id,
                '-' AS course_name,
                'All Students' AS batch_name,
                COUNT(a.student_id) AS marked,
                SUM(CASE WHEN a.status='P' THEN 1 ELSE 0 END) AS present,
                SUM(CASE WHEN a.status='A' THEN 1 ELSE 0 END) AS absent,
                u.full_name AS marked_by_name,
                MAX(a.marked_at) AS last_marked_at
            FROM attendance a
            LEFT JOIN users u ON u.id = a.marked_by
            WHERE a.att_date=?
            GROUP BY a.marked_by
            ORDER BY last_marked_at DESC
        """, (att_date, att_date))
        rows = cur.fetchall()

    conn.close()

    # Fix None values
    final_rows = []
    for r in rows:
        final_rows.append({
            "att_date": r["att_date"],
            "batch_id": r["batch_id"],
            "course_name": r["course_name"],
            "batch_name": r["batch_name"],
            "marked": r["marked"] or 0,
            "present": r["present"] or 0,
            "absent": r["absent"] or 0,
            "marked_by_name": r["marked_by_name"] or "-",
            "last_marked_at": r["last_marked_at"] or "-"
        })

    return render_template(
        "audit.html",
        att_date=att_date,
        batches=batches,
        batch_id=batch_id,
        rows=final_rows
    )

# -------- DAILY REPORT --------

@app.route("/report/daily", methods=["GET"])
@login_required
def report_daily():
    att_date = request.args.get("date") or str(date.today())
    batch_id = request.args.get("batch_id")

    conn = get_conn()
    cur = conn.cursor()

    # Load batches for dropdown
    cur.execute("""
        SELECT b.id, b.batch_name, c.course_name
        FROM batches b
        JOIN courses c ON c.id=b.course_id
        WHERE b.is_active=1
        ORDER BY c.course_name, b.batch_name
    """)
    batches = cur.fetchall()

    if batch_id:
        cur.execute("""
            SELECT s.registration_number, s.full_name,
                   COALESCE(a.status,'A') AS status
            FROM students s
            JOIN student_batches sb ON sb.student_id=s.id
            LEFT JOIN attendance a
              ON a.student_id = s.id AND a.att_date = ?
            WHERE sb.batch_id=? AND s.is_active=1
            ORDER BY s.full_name
        """, (att_date, batch_id))
    else:
        cur.execute("""
            SELECT s.registration_number, s.full_name,
                   COALESCE(a.status,'A') AS status
            FROM students s
            LEFT JOIN attendance a
              ON a.student_id = s.id AND a.att_date = ?
            WHERE s.is_active=1
            ORDER BY s.full_name
        """, (att_date,))

    rows = cur.fetchall()
    present = sum(1 for r in rows if r["status"] == "P")
    absent = sum(1 for r in rows if r["status"] != "P")

    conn.close()
    return render_template("report_daily.html",
                           rows=rows, att_date=att_date,
                           present=present, absent=absent,
                           batches=batches, batch_id=batch_id)

# -------- MONTHLY REPORT --------

@app.route("/report/monthly", methods=["GET"])
@login_required
def report_monthly():
    # format: YYYY-MM
    month = request.args.get("month") or str(date.today())[:7]

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT s.registration_number, s.full_name,
               SUM(CASE WHEN a.status='P' THEN 1 ELSE 0 END) AS present_days,
               SUM(CASE WHEN a.status='A' THEN 1 ELSE 0 END) AS absent_days,
               COUNT(a.id) AS marked_days
        FROM students s
        LEFT JOIN attendance a
          ON a.student_id = s.id AND substr(a.att_date, 1, 7) = ?
        WHERE s.is_active=1
        GROUP BY s.id
        ORDER BY s.full_name
    """, (month,))
    rows = cur.fetchall()

    conn.close()
    return render_template("report_monthly.html", rows=rows, month=month)

if __name__ == "__main__":
    app.run(debug=True)