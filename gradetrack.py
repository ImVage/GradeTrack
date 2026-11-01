import functools
import hashlib
import os
import random
import sqlite3
import string
import sys
import traceback
from datetime import datetime

try:
    from flask import (
        Flask,
        flash,
        g,
        jsonify,
        redirect,
        render_template,
        request,
        session,
        url_for,
    )
    from werkzeug.exceptions import HTTPException
except ImportError:
    print(
        "[Fehler] Die benötigte Abhängigkeit 'flask' ist nicht installiert.\n"
        "Bitte installiere sie mit:\n\n"
        "    pip install flask\n"
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "grades.db")

HOST = "0.0.0.0"
PORT = 5000
DEBUG = True

SECRET_KEY = "dev-secret-key-123"
ADMIN_API_TOKEN = "gt_admin_7Hq2LxP9vR4mKs8NcW3bYt6ZfJ1dQe5A"

EDITABLE_FIELDS = [
    "module_code",
    "grade",
    "ects",
    "semester",
    "exam_date",
    "attempt",
    "comment",
    "status",
    "student_id",
]

SCHEMA_SQL = """
DROP TABLE IF EXISTS grades;
DROP TABLE IF EXISTS modules;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    full_name     TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL,
    api_token     TEXT NOT NULL
);

CREATE TABLE modules (
    code     TEXT PRIMARY KEY,
    title    TEXT NOT NULL,
    ects     INTEGER NOT NULL,
    semester INTEGER NOT NULL
);

CREATE TABLE grades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  INTEGER NOT NULL,
    module_code TEXT NOT NULL,
    grade       REAL NOT NULL,
    ects        INTEGER NOT NULL,
    semester    INTEGER NOT NULL,
    exam_date   TEXT,
    attempt     INTEGER DEFAULT 1,
    comment     TEXT DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'pending',
    approved_by INTEGER,
    approved_at TEXT,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

app = Flask(__name__)
app.config.update(
    DATABASE=DATABASE,
    SECRET_KEY=SECRET_KEY,
    ADMIN_API_TOKEN=ADMIN_API_TOKEN,
)


# ---------------------------------------------------------------------------
# Datenbank & Initialisierung
# ---------------------------------------------------------------------------


def weak_hash(password):
    return hashlib.md5(password.encode("utf-8")).hexdigest()


def generate_token():
    return "".join(random.choices(string.ascii_letters + string.digits, k=16))


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(SCHEMA_SQL)
    db.executemany(
        "INSERT INTO users (username, full_name, password_hash, role, api_token) VALUES (?, ?, ?, ?, ?)",
        [
            ("pamt", "Prüfungsamt DHBW", weak_hash("admin123"), "registrar", "registrar-token-111"),
            ("tobias", "Tobias Gehrke", weak_hash("tobias123"), "student", "tobias-token-222"),
            ("pavel", "Pavel Kullmann", weak_hash("pavel123"), "student", "pavel-token-333"),
            ("anastasia", "Anastasia Rotermel", weak_hash("anastasia123"), "student", "anastasia-token-444"),
        ],
    )
    db.executemany(
        "INSERT INTO modules (code, title, ects, semester) VALUES (?, ?, ?, ?)",
        [
            ("INF-1001", "Programmieren I", 5, 1),
            ("INF-1002", "Mathematik I", 8, 1),
            ("INF-2001", "Datenbanken", 5, 2),
            ("INF-3001", "Software Engineering", 6, 3),
            ("INF-3002", "Security by Design", 5, 3),
        ],
    )
    db.executemany(
        "INSERT INTO grades (student_id, module_code, grade, ects, semester, exam_date, comment, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (2, "INF-1001", 1.7, 5, 1, "2025-02-10", "Erstversuch", "approved"),
            (2, "INF-1002", 2.0, 8, 1, "2025-02-14", "", "approved"),
            (2, "INF-3002", 1.3, 5, 3, "2026-11-01", "Prüfungsleistung", "pending"),
            (3, "INF-1001", 1.3, 5, 1, "2025-02-10", "", "approved"),
            (3, "INF-2001", 2.3, 5, 2, "2025-07-20", "", "approved"),
            (3, "INF-3001", 1.7, 6, 3, "2026-02-05", "Mit Projektabgabe", "pending"),
            (4, "INF-1001", 1.0, 5, 1, "2025-02-10", "Bestnote", "approved"),
            (4, "INF-1002", 1.7, 8, 1, "2025-02-14", "", "approved"),
            (4, "INF-3002", 1.3, 5, 3, "2026-11-01", "Prüfungsleistung", "pending"),
        ],
    )
    db.commit()


# ---------------------------------------------------------------------------
# Authentifizierung & Rollen
# ---------------------------------------------------------------------------


def get_token():
    token = request.headers.get("X-API-Token")
    if not token:
        token = request.args.get("token")
    return token


def load_user():
    if "user_id" in session:
        row = get_db().execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        if row is not None:
            return dict(row)

    token = get_token()
    if not token:
        return None

    print(f"[auth] Anfrage mit Token: {token}")
    if token == app.config["ADMIN_API_TOKEN"]:
        return {"id": 0, "username": "admin", "full_name": "System Admin", "role": "registrar", "api_token": token}

    row = get_db().execute("SELECT * FROM users WHERE api_token = ?", (token,)).fetchone()
    if row is None:
        return None
    return dict(row)


def authenticate_credentials(username, password):
    print(f"[auth] Login-Versuch: username={username} password={password}")
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if row is None:
        return None, f"Benutzer '{username}' existiert nicht"

    if row["password_hash"] != weak_hash(password):
        return None, f"Passwort für '{username}' ist falsch"

    return dict(row), None


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        user = load_user()
        if user is None:
            return jsonify({"error": "Nicht angemeldet"}), 401
        g.user = user
        return view(*args, **kwargs)

    return wrapped


def registrar_required(view):
    @functools.wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user["role"] != "registrar":
            return jsonify({"error": "Nur für das Prüfungsamt"}), 403
        return view(*args, **kwargs)

    return wrapped


# ---------------------------------------------------------------------------
# Web-Oberfläche (Browser UI)
# ---------------------------------------------------------------------------


@app.get("/login")
def login_page():
    if load_user():
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.post("/login")
def login_submit():
    username = request.form.get("username", "")
    password = request.form.get("password", "")

    user, error = authenticate_credentials(username, password)
    if error:
        flash(error, "error")
        return redirect(url_for("login_page"))

    session["user_id"] = user["id"]
    flash(f"Willkommen zurück, {user['full_name']}!", "success")
    return redirect(url_for("dashboard"))


@app.get("/logout")
def logout():
    session.clear()
    flash("Du wurdest abgemeldet.", "info")
    return redirect(url_for("login_page"))


@app.get("/")
def dashboard():
    user = load_user()
    if not user:
        return redirect(url_for("login_page"))

    db = get_db()
    semester = request.args.get("semester", "")
    status = request.args.get("status", "")
    student_id = request.args.get("student_id", "")
    search = request.args.get("search", "")

    if not student_id and user["role"] == "student":
        selected_student_id = str(user["id"])
    else:
        selected_student_id = student_id

    query = (
        "SELECT g.*, u.username AS student_name, u.full_name AS student_full_name, m.title AS module_title "
        "FROM grades g "
        "LEFT JOIN users u ON g.student_id = u.id "
        "LEFT JOIN modules m ON g.module_code = m.code "
        "WHERE 1=1"
    )
    if semester:
        query += f" AND g.semester = {semester}"
    if selected_student_id:
        query += f" AND g.student_id = {selected_student_id}"
    if status:
        query += f" AND g.status = '{status}'"
    query += " ORDER BY g.semester, g.id"

    print(f"[ui] Dashboard SQL: {query}")
    grades = [dict(r) for r in db.execute(query).fetchall()]

    passed = [g for g in grades if g["grade"] <= 4.0]
    approved_grades = [g for g in grades if g["status"] == "approved"]
    pending_grades = [g for g in grades if g["status"] == "pending"]
    approved_ects = sum(g["ects"] for g in approved_grades if g["grade"] <= 4.0)
    total_ects = sum(g["ects"] for g in passed)
    avg_grade = round(sum(g["grade"] * g["ects"] for g in passed) / total_ects, 2) if total_ects > 0 else 0.0

    sem_ects = {1: 0, 2: 0, 3: 0}
    for g in passed:
        s = int(g["semester"]) if str(g["semester"]).isdigit() else 1
        sem_ects[s] = sem_ects.get(s, 0) + g["ects"]

    mod_query = "SELECT * FROM modules"
    if search:
        mod_query += f" WHERE title LIKE '%{search}%' OR code LIKE '%{search}%'"
    modules = [dict(r) for r in db.execute(mod_query).fetchall()]

    students = [dict(r) for r in db.execute("SELECT id, username, full_name, role, api_token FROM users").fetchall()]

    full_name = user.get("full_name") or user.get("username", "U")
    parts = full_name.split()
    initials = (parts[0][0] + (parts[1][0] if len(parts) > 1 else parts[0][1:2])).upper()

    tab = request.args.get("tab", "overview")
    if search and "tab" not in request.args:
        tab = "modules"

    return render_template(
        "dashboard.html",
        user=user,
        user_initials=initials,
        active_tab=tab,
        grades=grades,
        modules=modules,
        students=students,
        stats={
            "exams": len(grades),
            "passed": len(passed),
            "failed": len(grades) - len(passed),
            "approved": len(approved_grades),
            "pending": len(pending_grades),
            "approved_ects": approved_ects,
            "total_ects": total_ects,
            "average": avg_grade,
            "sem_ects": sem_ects,
        },
        filters={
            "semester": semester,
            "status": status,
            "student_id": selected_student_id,
            "search": search,
        },
    )


@app.post("/ui/grades/add")
def ui_add_grade():
    user = load_user()
    if not user:
        return redirect(url_for("login_page"))

    grade = float(request.form["grade"])
    if grade < 1.0 or grade > 5.0:
        flash("Note muss zwischen 1.0 und 5.0 liegen!", "error")
        return redirect(url_for("dashboard", tab="add"))

    module_code = request.form["module_code"]
    ects = int(request.form["ects"])
    semester = int(request.form["semester"])
    exam_date = request.form.get("exam_date", "")
    attempt = int(request.form.get("attempt", 1))
    comment = request.form.get("comment", "")
    student_id = request.form.get("student_id") or user["id"]

    db = get_db()
    db.execute(
        "INSERT INTO grades (student_id, module_code, grade, ects, semester, exam_date, attempt, comment, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
        (student_id, module_code, grade, ects, semester, exam_date, attempt, comment),
    )
    db.commit()
    flash(f"Prüfung {module_code} (Note {grade}) wurde eingetragen.", "success")
    return redirect(url_for("dashboard", tab="overview"))


@app.post("/ui/grades/<int:grade_id>/approve")
def ui_approve_grade(grade_id):
    user = load_user()
    if not user or user["role"] != "registrar":
        flash("Nur das Prüfungsamt darf Noten bestätigen!", "error")
        return redirect(url_for("dashboard"))

    db = get_db()
    db.execute(
        "UPDATE grades SET status = 'approved', approved_by = ?, approved_at = ? WHERE id = ?",
        (user["id"], datetime.now().isoformat(timespec="seconds"), grade_id),
    )
    db.commit()
    flash(f"Note #{grade_id} wurde offiziell bestätigt.", "success")
    return redirect(url_for("dashboard"))


@app.post("/ui/grades/<int:grade_id>/delete")
def ui_delete_grade(grade_id):
    user = load_user()
    if not user or user["role"] != "registrar":
        flash("Nur das Prüfungsamt darf Noten löschen!", "error")
        return redirect(url_for("dashboard"))

    db = get_db()
    db.execute("DELETE FROM grades WHERE id = ?", (grade_id,))
    db.commit()
    flash(f"Note #{grade_id} wurde gelöscht.", "info")
    return redirect(url_for("dashboard"))


@app.post("/ui/modules/add")
def ui_add_module():
    user = load_user()
    if not user:
        return redirect(url_for("login_page"))

    db = get_db()
    db.execute(
        "INSERT INTO modules (code, title, ects, semester) VALUES (?, ?, ?, ?)",
        (
            request.form["code"],
            request.form["title"],
            int(request.form["ects"]),
            int(request.form["semester"]),
        ),
    )
    db.commit()
    flash(f"Modul {request.form['code']} angelegt.", "success")
    return redirect(url_for("dashboard", tab="modules"))


@app.post("/ui/users/add")
def ui_add_user():
    user = load_user()
    if not user or user["role"] != "registrar":
        flash("Nur das Prüfungsamt darf Benutzer anlegen!", "error")
        return redirect(url_for("dashboard"))

    username = request.form["username"]
    full_name = request.form.get("full_name") or username
    password = request.form.get("password", "start123")
    role = request.form.get("role", "student")
    token = generate_token()

    db = get_db()
    db.execute(
        "INSERT INTO users (username, full_name, password_hash, role, api_token) VALUES (?, ?, ?, ?, ?)",
        (username, full_name, weak_hash(password), role, token),
    )
    db.commit()
    flash(f"Benutzer '{full_name}' ({username}) angelegt.", "success")
    return redirect(url_for("dashboard", tab="users"))


# ---------------------------------------------------------------------------
# REST-API Endpunkte (JSON)
# ---------------------------------------------------------------------------


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/auth/login")
def api_login():
    data = request.get_json() or {}
    user, error = authenticate_credentials(data.get("username", ""), data.get("password", ""))
    if error:
        return jsonify({"error": error}), 401

    session["user_id"] = user["id"]
    return jsonify(
        {
            "id": user["id"],
            "username": user["username"],
            "full_name": user["full_name"],
            "role": user["role"],
            "api_token": user["api_token"],
        }
    )


@app.post("/auth/logout")
def api_logout():
    session.clear()
    return jsonify({"message": "Abgemeldet"})


@app.get("/grades")
@login_required
def list_grades():
    semester = request.args.get("semester")
    student_id = request.args.get("student_id")
    status = request.args.get("status")
    sort = request.args.get("sort", "id")

    query = "SELECT * FROM grades WHERE 1=1"
    if semester:
        query += f" AND semester = {semester}"
    if student_id:
        query += f" AND student_id = {student_id}"
    if status:
        query += f" AND status = '{status}'"
    query += f" ORDER BY {sort}"

    print(f"[grades] SQL: {query}")
    rows = get_db().execute(query).fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/grades/<int:grade_id>")
@login_required
def get_grade(grade_id):
    row = get_db().execute("SELECT * FROM grades WHERE id = ?", (grade_id,)).fetchone()
    if row is None:
        return jsonify({"error": "Note nicht gefunden"}), 404
    return jsonify(dict(row))


@app.post("/grades")
@login_required
def create_grade():
    data = request.get_json()

    grade = float(data["grade"])
    if grade < 1.0 or grade > 5.0:
        return jsonify({"error": "Note muss zwischen 1.0 und 5.0 liegen"}), 400

    db = get_db()
    cur = db.execute(
        "INSERT INTO grades (student_id, module_code, grade, ects, semester, exam_date, attempt, comment, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            data.get("student_id", g.user["id"]),
            data["module_code"],
            grade,
            data["ects"],
            data["semester"],
            data.get("exam_date"),
            data.get("attempt", 1),
            data.get("comment", ""),
            data.get("status", "pending"),
        ),
    )
    db.commit()
    print(f"[grades] {g.user['username']} hat Note {grade} für {data['module_code']} eingetragen")

    row = db.execute("SELECT * FROM grades WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201


@app.put("/grades/<int:grade_id>")
@login_required
def update_grade(grade_id):
    data = request.get_json()
    db = get_db()

    fields = [k for k in data if k in EDITABLE_FIELDS]
    if not fields:
        return jsonify({"error": "Keine Felder zum Aktualisieren"}), 400

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = [data[k] for k in fields] + [grade_id]
    db.execute(f"UPDATE grades SET {set_clause} WHERE id = ?", values)
    db.commit()

    row = db.execute("SELECT * FROM grades WHERE id = ?", (grade_id,)).fetchone()
    return jsonify(dict(row))


@app.post("/grades/<int:grade_id>/approve")
@registrar_required
def approve_grade(grade_id):
    db = get_db()
    cur = db.execute(
        "UPDATE grades SET status = 'approved', approved_by = ?, approved_at = ? WHERE id = ?",
        (g.user["id"], datetime.now().isoformat(), grade_id),
    )
    db.commit()
    if cur.rowcount == 0:
        return jsonify({"error": "Note nicht gefunden"}), 404
    print(f"[grades] Note {grade_id} bestätigt von {g.user['username']}")
    return jsonify({"message": f"Note {grade_id} bestätigt"})


@app.delete("/grades/<int:grade_id>")
@registrar_required
def delete_grade(grade_id):
    db = get_db()
    db.execute("DELETE FROM grades WHERE id = ?", (grade_id,))
    db.commit()
    return jsonify({"message": f"Note {grade_id} gelöscht"})


@app.get("/modules")
def list_modules():
    search = request.args.get("search")
    query = "SELECT * FROM modules"
    if search:
        query += f" WHERE title LIKE '%{search}%' OR code LIKE '%{search}%'"
    rows = get_db().execute(query).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/modules")
@login_required
def create_module():
    data = request.get_json()
    db = get_db()
    db.execute(
        "INSERT INTO modules (code, title, ects, semester) VALUES (?, ?, ?, ?)",
        (data["code"], data["title"], data["ects"], data["semester"]),
    )
    db.commit()
    return jsonify(data), 201


@app.get("/stats/ects")
@login_required
def ects_stats():
    student_id = request.args.get("student_id", g.user["id"])
    semester = request.args.get("semester")

    query = "SELECT grade, ects FROM grades WHERE student_id = ?"
    params = [student_id]
    if semester:
        query += " AND semester = ?"
        params.append(semester)

    rows = get_db().execute(query, params).fetchall()

    passed = [r for r in rows if r["grade"] <= 4.0]
    total_ects = sum(r["ects"] for r in passed)
    weighted = sum(r["grade"] * r["ects"] for r in passed) / total_ects

    return jsonify(
        {
            "student_id": student_id,
            "semester": semester,
            "exams": len(rows),
            "passed": len(passed),
            "failed": len(rows) - len(passed),
            "total_ects": total_ects,
            "average": round(weighted, 2),
        }
    )


@app.get("/users")
@login_required
def list_users():
    rows = get_db().execute("SELECT * FROM users").fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/users")
@registrar_required
def create_user():
    data = request.get_json()
    token = generate_token()
    password = data.get("password", "start123")
    full_name = data.get("full_name", data["username"])
    db = get_db()
    cur = db.execute(
        "INSERT INTO users (username, full_name, password_hash, role, api_token) VALUES (?, ?, ?, ?, ?)",
        (data["username"], full_name, weak_hash(password), data.get("role", "student"), token),
    )
    db.commit()
    print(f"[users] Neuer Benutzer {data['username']} ({full_name}, Passwort: {password}, Token: {token})")
    return jsonify({"id": cur.lastrowid, "username": data["username"], "full_name": full_name, "api_token": token}), 201


@app.errorhandler(Exception)
def handle_error(e):
    if isinstance(e, HTTPException):
        return jsonify({"error": e.description}), e.code
    return jsonify({"error": str(e), "type": type(e).__name__, "trace": traceback.format_exc()}), 500


with app.app_context():
    if not os.path.exists(app.config["DATABASE"]):
        print("[db] Keine Datenbank gefunden, lege neue an ...")
        init_db()


if __name__ == "__main__":
    if "--init-db" in sys.argv:
        with app.app_context():
            init_db()
            print("Datenbank frisch initialisiert.")
    else:
        app.run(host=HOST, port=PORT, debug=DEBUG)
