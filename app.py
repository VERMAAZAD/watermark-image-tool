from dotenv import load_dotenv
load_dotenv()

import os
import csv
import time
import stat
import json
import shutil
import threading
import subprocess
import smtplib
import secrets
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from uuid import uuid4
import random
from flask import Flask, request, jsonify, send_from_directory, render_template, redirect, url_for, session
from flask_cors import CORS
from functools import wraps
from opencv_engine import add_images_to_folders

# ================== CONFIG ==================
USERNAME = os.environ.get("DASHBOARD_USERNAME", "Chirag")
PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "Chirag!@KH1290")
MASTER_USERNAME = os.environ.get("MASTER_USERNAME", "master")
MASTER_PASSWORD = os.environ.get("MASTER_PASSWORD", "Master!@SecurePass")
SECRET_KEY = os.environ.get("FLASK_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("FLASK_SECRET_KEY is not set in .env")

# ================== EMAIL / OTP CONFIG ==================
SMTP_HOST     = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER     = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
MASTER_EMAIL  = os.environ.get("MASTER_EMAIL", "")
OTP_EXPIRY    = 300  # 5 minutes

# In-memory OTP store: token -> {otp, expires, username, is_master, display_name}
OTP_STORE = {}

app = Flask(__name__, static_folder="static")
CORS(app)
app.secret_key = SECRET_KEY

from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

OUTPUT_FOLDER = "images"
UPLOAD_BASE = "uploads/base"
UPLOAD_LOGO = "uploads/logo"
USERS_FILE = "data/users.json"
JOBS_LOG_FILE = "data/jobs_log.json"

DELETE_AFTER_SECONDS = 5 * 24 * 60 * 60
CLEANUP_INTERVAL = 60 * 60

os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_BASE, exist_ok=True)
os.makedirs(UPLOAD_LOGO, exist_ok=True)
os.makedirs("data", exist_ok=True)

# ================== USER STORE ==================
def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, "r") as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

def load_jobs_log():
    if not os.path.exists(JOBS_LOG_FILE):
        return []
    with open(JOBS_LOG_FILE, "r") as f:
        return json.load(f)

def save_jobs_log(log):
    with open(JOBS_LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)

JOBS = {}

# ================== OTP HELPERS ==================
def generate_otp():
    return str(secrets.randbelow(900000) + 100000)  # always 6 digits

def send_otp_email(otp, username, is_master):
    if not MASTER_EMAIL or not SMTP_USER or not SMTP_PASSWORD:
        app.logger.warning("OTP email not configured — check SMTP_USER, SMTP_PASSWORD, MASTER_EMAIL in .env")
        return False

    role = "Master Admin" if is_master else f"User: {username}"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;background:#0a0a0b;border:1px solid #222;border-radius:12px;overflow:hidden">
      <div style="background:#6366f1;padding:20px 28px">
        <h2 style="color:#fff;margin:0;font-size:18px">🔐 Login OTP</h2>
      </div>
      <div style="padding:28px">
        <p style="color:#a1a1aa;font-size:14px;margin:0 0 20px">
          A login attempt was made for <strong style="color:#fafafa">{role}</strong> on the Watermark Generator dashboard.
        </p>
        <div style="background:#18181b;border:1px solid #333;border-radius:10px;padding:20px;text-align:center;margin-bottom:20px">
          <p style="color:#6b7280;font-size:12px;margin:0 0 8px;text-transform:uppercase;letter-spacing:.1em">Your OTP Code</p>
          <p style="font-size:36px;font-weight:700;letter-spacing:10px;color:#6366f1;margin:0;font-family:monospace">{otp}</p>
        </div>
        <p style="color:#52525b;font-size:12px;margin:0">
          ⏱ Expires in <strong>5 minutes</strong>. If you did not attempt this login, ignore this email.
        </p>
      </div>
    </div>
    """
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[Watermark] OTP: {otp} — Login by {username}"
        msg["From"] = SMTP_USER
        msg["To"] = MASTER_EMAIL
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, MASTER_EMAIL, msg.as_string())
        return True
    except Exception as e:
        app.logger.error(f"Failed to send OTP email: {e}")
        return False

def cleanup_otp_store():
    """Remove expired OTPs periodically."""
    while True:
        now = time.time()
        expired = [t for t, v in OTP_STORE.items() if v["expires"] < now]
        for t in expired:
            OTP_STORE.pop(t, None)
        time.sleep(60)

# ================== AUTH DECORATORS ==================
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if request.path.startswith("/api/job-status"):
            return f(*args, **kwargs)

        if not session.get("logged_in"):
            return redirect(url_for("login"))

        if not session.get("is_master"):
            username = session.get("username")
            users = load_users()
            user = users.get(username)
            if not user or not user.get("active", True):
                session.clear()
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Account disabled"}), 403
                return redirect(url_for("login"))

        return f(*args, **kwargs)
    return wrapper

def master_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("is_master"):
            return jsonify({"error": "Master access required"}), 403
        return f(*args, **kwargs)
    return wrapper

# ================== AUTH ROUTES ==================
@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "")

        pending = None

        # Master login check
        if u == MASTER_USERNAME and p == MASTER_PASSWORD:
            pending = {"username": u, "is_master": True, "display_name": "Master Admin"}

        else:
            # Regular user check
            users = load_users()
            if u in users and users[u]["password"] == p:
                if not users[u].get("active", True):
                    error = "Your account has been disabled."
                else:
                    pending = {
                        "username": u,
                        "is_master": False,
                        "display_name": users[u].get("display_name", u)
                    }
            else:
                error = "Invalid username or password"

        if pending:
            # Generate OTP and send email
            otp = generate_otp()
            token = secrets.token_urlsafe(32)
            OTP_STORE[token] = {
                "otp": otp,
                "expires": time.time() + OTP_EXPIRY,
                **pending
            }
            sent = send_otp_email(otp, pending["username"], pending["is_master"])
            if not sent:
                # If email fails, still show OTP page but warn
                error = "OTP email could not be sent — check SMTP config. Contact admin."
                # In dev mode you could log otp here; remove in production
                app.logger.warning(f"DEV ONLY — OTP for {u}: {otp}")

            return redirect(url_for("verify_otp", token=token))

    return render_template("login.html", error=error)


@app.route("/verify-otp/<token>", methods=["GET", "POST"])
def verify_otp(token):
    entry = OTP_STORE.get(token)

    if not entry:
        return render_template("otp.html", error="Invalid or expired session. Please log in again.", token=token, expired=True)

    if time.time() > entry["expires"]:
        OTP_STORE.pop(token, None)
        return render_template("otp.html", error="OTP has expired. Please log in again.", token=token, expired=True)

    error = ""
    if request.method == "POST":
        submitted = request.form.get("otp", "").strip()
        if submitted == entry["otp"]:
            # OTP correct — create real session
            OTP_STORE.pop(token, None)
            session["logged_in"] = True
            session["is_master"] = entry["is_master"]
            session["username"] = entry["username"]
            session["display_name"] = entry["display_name"]
            if entry["is_master"]:
                return redirect(url_for("master_dashboard"))
            return redirect(url_for("home"))
        else:
            error = "Incorrect OTP. Please try again."

    # Calculate seconds remaining
    remaining = max(0, int(entry["expires"] - time.time()))
    username_display = entry.get("display_name", entry["username"])
    return render_template("otp.html", token=token, error=error, remaining=remaining,
                           username=username_display, expired=False)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ================== MAIN APP ROUTES ==================
@app.route("/")
@login_required
def home():
    return render_template("index.html",
        username=session.get("display_name", ""),
        is_master=session.get("is_master", False)
    )

@app.route("/generate", methods=["POST"])
@login_required
def generate():
    base = request.files.getlist("baseImages")
    logo = request.files.get("logoImage")
    folder_name = request.form.get("folderName", "output")

    if not base or not logo:
        return jsonify({"error": "Images required"}), 400

    base_paths = []
    for f in base:
        path = os.path.join(UPLOAD_BASE, f.filename)
        f.save(path)
        base_paths.append(path)

    logo_path = os.path.join(UPLOAD_LOGO, logo.filename)
    logo.save(logo_path)

    num_folders = int(request.form.get("folders", 10))
    pos_x = int(request.form.get("posX", 0))
    pos_y = int(request.form.get("posY", 0))

    job_id = str(uuid4())
    username = session.get("username", "unknown")
    JOBS[job_id] = {"status": "queued", "username": username}

    log = load_jobs_log()
    log.append({
        "job_id": job_id,
        "username": username,
        "folder_name": folder_name,
        "num_images": num_folders,
        "status": "queued",
        "created_at": time.time(),
        "base_files": [os.path.basename(p) for p in base_paths],
        "logo_file": os.path.basename(logo_path)
    })
    save_jobs_log(log)

    def task(base_paths, logo_path, folder_name, num_folders, pos_x, pos_y):
        try:
            JOBS[job_id]["status"] = "processing"
            _update_job_log(job_id, "processing")
            add_images_to_folders(
                base_image_paths=base_paths,
                overlay_image_path=logo_path,
                num_images=num_folders,
                coordinates=[(pos_x, pos_y)],
                folder_base_name=folder_name
            )
            JOBS[job_id]["status"] = "done"
            _update_job_log(job_id, "done")
        except Exception as e:
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = str(e)
            _update_job_log(job_id, "error", str(e))

    threading.Thread(target=task, args=(base_paths, logo_path, folder_name, num_folders, pos_x, pos_y), daemon=True).start()
    return jsonify({"success": True, "job_id": job_id})

def _update_job_log(job_id, status, error=None):
    log = load_jobs_log()
    for entry in log:
        if entry["job_id"] == job_id:
            entry["status"] = status
            entry["updated_at"] = time.time()
            if error:
                entry["error"] = error
            break
    save_jobs_log(log)

@app.route("/api/job-status/<job_id>")
def job_status(job_id):
    return jsonify(JOBS.get(job_id, {"status": "not_found"}))

@app.route("/api/all-results")
@login_required
def api_all_results():
    username = session.get("username", "")
    log = load_jobs_log()
    
    # Build a set of folder names that belong to this user
    user_folders = {
        j.get("folder_name") 
        for j in log 
        if j.get("username") == username and j.get("folder_name")
    }

    all_tables = []
    for folder in os.listdir(OUTPUT_FOLDER):
        # Skip folders that don't belong to this user
        if folder not in user_folders:
            continue
        folder_path = os.path.join(OUTPUT_FOLDER, folder)
        if not os.path.isdir(folder_path):
            continue
        csv_path = os.path.join(folder_path, f"{folder}.csv")
        if not os.path.exists(csv_path):
            continue
        rows = []
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                rows.append(row)
        all_tables.append({
            "name": folder,
            "rows": rows,
            "mtime": os.path.getmtime(csv_path)
        })
    all_tables.sort(key=lambda x: x["mtime"], reverse=True)
    return jsonify(all_tables)


@app.route("/api/app-size")
@login_required
def get_app_size():
    folder_path = "/var/www/watermark"
    try:
        result = subprocess.check_output(["du", "-sh", folder_path], text=True)
        size = result.split()[0]
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"folder": "Storage Used", "size": size})

@app.route("/results")
@login_required
def results_page():
    return render_template("results.html",
        username=session.get("display_name", ""),
        is_master=session.get("is_master", False)
    )

@app.route("/api/delete-table", methods=["POST"])
@login_required
def delete_table():
    data = request.json
    table = data.get("table")
    if not table:
        return jsonify({"success": False, "error": "Table name missing"}), 400

    if not session.get("is_master"):
        username = session.get("username", "")
        log = load_jobs_log()
        owner = next((j.get("username") for j in log if j.get("folder_name") == table), None)
        if owner and owner != username:
            return jsonify({"success": False, "error": "Not authorized"}), 403

    folder_path = os.path.join(OUTPUT_FOLDER, table)
    if not os.path.exists(folder_path):
        return jsonify({"success": False, "error": "Folder not found"}), 404

    try:
        shutil.rmtree(folder_path, onerror=handle_remove_readonly)
    except Exception as e:
        return jsonify({"success": False, "error": f"Failed to delete: {str(e)}"}), 500

    # Remove from log and delete uploads
    log = load_jobs_log()
    job_entry = next((j for j in log if j.get("folder_name") == table), None)
    if job_entry:
        delete_job_uploads(job_entry)
    log = [j for j in log if j.get("folder_name") != table]
    save_jobs_log(log)

    return jsonify({"success": True})
@app.route("/images/<folder>/<filename>")
def serve_images(folder, filename):
    return send_from_directory(os.path.join(OUTPUT_FOLDER, folder), filename)

# ================== MASTER DASHBOARD ROUTES ==================
@app.route("/master")
@login_required
@master_required
def master_dashboard():
    return render_template("master.html", display_name=session.get("display_name", "Master"))

@app.route("/api/master/users", methods=["GET"])
@login_required
@master_required
def api_get_users():
    users = load_users()
    result = []
    log = load_jobs_log()
    for username, data in users.items():
        user_jobs = [j for j in log if j.get("username") == username]
        result.append({
            "username": username,
            "display_name": data.get("display_name", username),
            "active": data.get("active", True),
            "created_at": data.get("created_at", 0),
            "total_jobs": len(user_jobs),
            "total_images": sum(j.get("num_images", 0) for j in user_jobs if j.get("status") == "done"),
            "last_active": max((j.get("updated_at", j.get("created_at", 0)) for j in user_jobs), default=0)
        })
    result.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return jsonify(result)

@app.route("/api/master/users", methods=["POST"])
@login_required
@master_required
def api_create_user():
    data = request.json
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    display_name = data.get("display_name", username).strip()

    if not username or not password:
        return jsonify({"success": False, "error": "Username and password required"}), 400

    users = load_users()
    if username in users:
        return jsonify({"success": False, "error": "Username already exists"}), 400
    if username == MASTER_USERNAME:
        return jsonify({"success": False, "error": "Reserved username"}), 400

    users[username] = {
        "password": password,
        "display_name": display_name,
        "active": True,
        "created_at": time.time()
    }
    save_users(users)
    return jsonify({"success": True})

@app.route("/api/master/users/<username>", methods=["PUT"])
@login_required
@master_required
def api_update_user(username):
    data = request.json
    users = load_users()
    if username not in users:
        return jsonify({"success": False, "error": "User not found"}), 404

    if "password" in data and data["password"]:
        users[username]["password"] = data["password"]
    if "display_name" in data:
        users[username]["display_name"] = data["display_name"]
    if "active" in data:
        users[username]["active"] = data["active"]

    save_users(users)
    return jsonify({"success": True})

@app.route("/api/master/users/<username>", methods=["DELETE"])
@login_required
@master_required
def api_delete_user(username):
    users = load_users()
    if username not in users:
        return jsonify({"success": False, "error": "User not found"}), 404
    del users[username]
    save_users(users)
    return jsonify({"success": True})

@app.route("/api/master/jobs", methods=["GET"])
@login_required
@master_required
def api_get_jobs():
    log = load_jobs_log()
    log.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return jsonify(log[:200])

@app.route("/api/master/stats", methods=["GET"])
@login_required
@master_required
def api_master_stats():
    users = load_users()
    log = load_jobs_log()
    done_jobs = [j for j in log if j.get("status") == "done"]
    total_images = sum(j.get("num_images", 0) for j in done_jobs)
    active_users = sum(1 for u in users.values() if u.get("active", True))
    week_ago = time.time() - 7 * 24 * 3600
    recent_jobs = [j for j in log if j.get("created_at", 0) > week_ago]
    return jsonify({
        "total_users": len(users),
        "active_users": active_users,
        "total_jobs": len(log),
        "total_images": total_images,
        "recent_jobs": len(recent_jobs),
        "recent_images": sum(j.get("num_images", 0) for j in recent_jobs if j.get("status") == "done")
    })



@app.route("/api/master/results", methods=["GET"])
@login_required
@master_required
def api_master_results():
    """
    Returns data grouped by user, then by job folder.
    Structure:
    [
      {
        "username": "john",
        "display_name": "John Doe",
        "jobs": [
          {
            "folder_name": "batch_01",
            "num_images": 10,
            "status": "done",
            "created_at": 1234567890,
            "images": [ { "name": "batch_01_1", "url": "...", "path": "/images/batch_01/batch_01_1.jpg" }, ... ],
            "mtime": 1234567890
          }
        ]
      }
    ]
    """
    log = load_jobs_log()
    users = load_users()

    folder_job_map = {}
    for entry in log:
        fname = entry.get("folder_name", "")
        if fname and fname not in folder_job_map:
            folder_job_map[fname] = entry

    user_jobs = {}  # username -> list of job dicts

    for folder in os.listdir(OUTPUT_FOLDER):
        folder_path = os.path.join(OUTPUT_FOLDER, folder)
        if not os.path.isdir(folder_path):
            continue

        job_entry = folder_job_map.get(folder, {})
        username = job_entry.get("username", "unknown")

        # Read CSV for image name+url pairs
        csv_path = os.path.join(folder_path, f"{folder}.csv")
        images = []
        if os.path.exists(csv_path):
            with open(csv_path, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)  # skip header
                for row in reader:
                    if len(row) >= 2:
                        img_name = row[0]
                        img_url = row[1]
                        # derive local serve path from url or filename
                        ext = ".jpg"
                        local_path = f"/images/{folder}/{img_name}{ext}"
                        images.append({
                            "name": img_name,
                            "url": img_url,
                            "path": local_path
                        })

        job = {
            "folder_name": folder,
            "num_images": job_entry.get("num_images", len(images)),
            "status": job_entry.get("status", "unknown"),
            "created_at": job_entry.get("created_at", os.path.getmtime(folder_path)),
            "images": images,
            "mtime": os.path.getmtime(folder_path)
        }

        if username not in user_jobs:
            user_jobs[username] = []
        user_jobs[username].append(job)

    # Sort each user's jobs newest first
    for uname in user_jobs:
        user_jobs[uname].sort(key=lambda x: x["created_at"], reverse=True)

    # Build final list sorted by most recent job across all users
    result = []
    for uname, jobs in user_jobs.items():
        user_data = users.get(uname, {})
        result.append({
            "username": uname,
            "display_name": user_data.get("display_name", uname),
            "total_jobs": len(jobs),
            "total_images": sum(j["num_images"] for j in jobs if j["status"] == "done"),
            "last_active": jobs[0]["created_at"] if jobs else 0,
            "jobs": jobs
        })

    result.sort(key=lambda x: x["last_active"], reverse=True)
    return jsonify(result)

@app.route("/api/master/jobs/<job_id>", methods=["DELETE"])
@login_required
@master_required
def api_delete_job(job_id):
    log = load_jobs_log()

    job_entry = next((j for j in log if j.get("job_id") == job_id), None)
    if not job_entry:
        return jsonify({"success": False, "error": "Job not found"}), 404

    log = [j for j in log if j.get("job_id") != job_id]
    save_jobs_log(log)
    JOBS.pop(job_id, None)

    # Delete output image folder
    folder_name = job_entry.get("folder_name", "")
    if folder_name:
        folder_path = os.path.join(OUTPUT_FOLDER, folder_name)
        if os.path.exists(folder_path) and os.path.isdir(folder_path):
            try:
                shutil.rmtree(folder_path, onerror=handle_remove_readonly)
            except Exception as e:
                return jsonify({"success": True, "warning": f"Log removed but folder deletion failed: {str(e)}"})

    # Delete uploaded base/logo files
    delete_job_uploads(job_entry)

    return jsonify({"success": True})
# ================== HELPERS ==================

def delete_job_uploads(job_entry):
    """Delete base and logo upload files associated with a job entry."""
    for fname in job_entry.get("base_files", []):
        fpath = os.path.join(UPLOAD_BASE, fname)
        if os.path.isfile(fpath):
            try:
                os.remove(fpath)
            except Exception as e:
                app.logger.warning(f"Could not delete base file {fpath}: {e}")

    logo = job_entry.get("logo_file", "")
    if logo:
        fpath = os.path.join(UPLOAD_LOGO, logo)
        if os.path.isfile(fpath):
            try:
                os.remove(fpath)
            except Exception as e:
                app.logger.warning(f"Could not delete logo file {fpath}: {e}")


def handle_remove_readonly(func, path, exc_info):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        time.sleep(0.1)
        func(path)


def cleanup_old_files():
    while True:
        now = time.time()

        # ── 1. Clean up expired OUTPUT folders ──────────────────────────
        log = load_jobs_log()
        log_changed = False

        for folder in os.listdir(OUTPUT_FOLDER):
            folder_path = os.path.join(OUTPUT_FOLDER, folder)
            if not os.path.isdir(folder_path):
                continue
            if now - os.path.getmtime(folder_path) > DELETE_AFTER_SECONDS:
                try:
                    shutil.rmtree(folder_path, onerror=handle_remove_readonly)
                    print(f"Auto-deleted expired folder: {folder}")

                    # Remove matching log entry and clean its uploads
                    job_entry = next((j for j in log if j.get("folder_name") == folder), None)
                    if job_entry:
                        delete_job_uploads(job_entry)
                        log = [j for j in log if j.get("folder_name") != folder]
                        log_changed = True

                except Exception as e:
                    print(f"Failed to delete {folder_path}: {e}")

        if log_changed:
            save_jobs_log(log)

        # ── 2. Clean up orphaned log entries (folder already gone) ──────
        log = load_jobs_log()
        orphans = [
            j for j in log
            if j.get("folder_name") and
               not os.path.isdir(os.path.join(OUTPUT_FOLDER, j["folder_name"]))
        ]
        if orphans:
            for orphan in orphans:
                delete_job_uploads(orphan)
                print(f"Removed orphaned log entry: {orphan.get('folder_name')}")
            log = [j for j in log if j not in orphans]
            save_jobs_log(log)

        # ── 3. Clean up orphaned upload files (no log entry references them) ──
        log = load_jobs_log()
        referenced_base  = {f for j in log for f in j.get("base_files", [])}
        referenced_logos = {j.get("logo_file") for j in log if j.get("logo_file")}

        for fname in os.listdir(UPLOAD_BASE):
            if fname not in referenced_base:
                fpath = os.path.join(UPLOAD_BASE, fname)
                if os.path.isfile(fpath) and now - os.path.getmtime(fpath) > DELETE_AFTER_SECONDS:
                    try:
                        os.remove(fpath)
                        print(f"Auto-deleted orphaned base upload: {fname}")
                    except Exception:
                        pass

        for fname in os.listdir(UPLOAD_LOGO):
            if fname not in referenced_logos:
                fpath = os.path.join(UPLOAD_LOGO, fname)
                if os.path.isfile(fpath) and now - os.path.getmtime(fpath) > DELETE_AFTER_SECONDS:
                    try:
                        os.remove(fpath)
                        print(f"Auto-deleted orphaned logo upload: {fname}")
                    except Exception:
                        pass

        time.sleep(CLEANUP_INTERVAL)


threading.Thread(target=cleanup_old_files, daemon=True).start()
threading.Thread(target=cleanup_otp_store, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001, debug=False)