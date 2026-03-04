from functools import wraps
from flask import session, redirect, url_for, flash
from db import get_conn

def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "danger")
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)
    return wrapper

def admin_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "danger")
            return redirect(url_for("login"))
        if session.get("role") != "admin":
            flash("Admin access required.", "danger")
            return redirect(url_for("dashboard"))
        return view_func(*args, **kwargs)
    return wrapper

def get_current_user():
    if "user_id" not in session:
        return None
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, full_name, username, role FROM users WHERE id=? AND is_active=1", (session["user_id"],))
    user = cur.fetchone()
    conn.close()
    return user