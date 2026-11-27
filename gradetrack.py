import functools
import getpass
import hashlib
import json
import logging
import os
import secrets
import sqlite3
import sys
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from typing import Any, cast

try:
    from flask import (
        Flask,
        Response,
        flash,
        g,
        jsonify,
        redirect,
        render_template,
        request,
        session,
        url_for,
    )
    from flask.typing import ResponseReturnValue
    from flask_wtf.csrf import CSRFProtect
    from pydantic import BaseModel, ValidationError
    from werkzeug.exceptions import HTTPException, UnsupportedMediaType
    from werkzeug.security import check_password_hash, generate_password_hash
except ImportError:
    print(
        "[Fehler] Die benötigte Abhängigkeit 'flask' ist nicht installiert.\n"
        "Bitte installiere sie mit:\n\n"
        "    pip install flask\n"
    )
    sys.exit(1)

import schemas

# Eine Datenbankzeile als Dictionary (Spaltenname -> Wert).
Zeile = dict[str, Any]
View = Callable[..., ResponseReturnValue]

# ---------------------------------------------------------------------------
# Logging: eine JSON-Zeile pro Ereignis nach STDOUT, maschinenlesbar.
# Niemals Passwörter, Tokens, Hashes oder SQL-Text loggen.
# ---------------------------------------------------------------------------


class JsonFormat(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        eintrag = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        eintrag.update(getattr(record, "felder", {}))
        if record.exc_info:
            eintrag["exception"] = self.formatException(record.exc_info)
        return json.dumps(eintrag, ensure_ascii=False)


log = logging.getLogger("gradetrack")
_ausgabe = logging.StreamHandler(sys.stdout)
_ausgabe.setFormatter(JsonFormat())
log.addHandler(_ausgabe)
log.setLevel(logging.INFO)
log.propagate = False


def protokolliere(ereignis: str, stufe: int = logging.INFO, **felder: object) -> None:
    log.log(stufe, ereignis, extra={"felder": felder})


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Im Container zeigt GRADETRACK_DB auf ein beschreibbares Volume (/data),
# lokal bleibt die Datenbank wie bisher neben dem Code.
DATABASE = os.environ.get("GRADETRACK_DB", os.path.join(BASE_DIR, "grades.db"))


def env_schalter(name: str, standard: bool) -> bool:
    """Liest einen Ja/Nein-Schalter aus der Umgebung. Unbekannte Werte sind ein Fehler."""
    wert = os.environ.get(name)
    if wert is None or wert == "":
        return standard
    if wert.lower() in ("1", "true", "ja", "yes"):
        return True
    if wert.lower() in ("0", "false", "nein", "no"):
        return False
    raise SystemExit(f"[Fehler] {name} muss 1 oder 0 sein, nicht {wert!r}.")


# Sichere Standardwerte: nur lokal erreichbar, kein Debug-Modus, Cookies nur über HTTPS.
# Abweichungen (z. B. 0.0.0.0 im Container) werden bewusst per Umgebungsvariable gesetzt.
HOST = os.environ.get("GRADETRACK_HOST", "127.0.0.1")
PORT = int(os.environ.get("GRADETRACK_PORT", "5000"))
DEBUG = env_schalter("GRADETRACK_DEBUG", False)
SECURE_COOKIES = env_schalter("GRADETRACK_SECURE_COOKIES", True)
# Beispielbenutzer mit bekannten Passwörtern nur, wenn ausdrücklich gewünscht (Demo, Tests).
DEMO_DATA = env_schalter("GRADETRACK_DEMO_DATA", False)

# Fail securely: Ohne eigenen, ausreichend langen Schlüssel startet die App nicht.
# Ein Standardwert im Code wäre für alle Installationen gleich und öffentlich bekannt.
SECRET_KEY = os.environ.get("GRADETRACK_SECRET_KEY", "")
if len(SECRET_KEY) < 32:
    raise SystemExit(
        "[Fehler] GRADETRACK_SECRET_KEY fehlt oder ist kürzer als 32 Zeichen.\n"
        "Erzeugen z. B. mit: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
    )

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
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=SECURE_COOKIES,
    SESSION_COOKIE_SAMESITE="Lax",
)
csrf = CSRFProtect(app)


def ohne_csrf(view: View) -> View:
    """Nimmt einen JSON-Endpunkt vom CSRF-Token aus.

    Schutz trotzdem: Das Session-Cookie ist SameSite=Lax und wird bei POST/PUT/DELETE von
    fremden Seiten nicht mitgeschickt; API-Clients melden sich per Token im Header an.
    Endpunkte mit Body verlangen zusätzlich application/json, was ein fremdes Formular
    nicht senden kann.
    """
    return cast(View, csrf.exempt(view))

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; object-src 'none'; base-uri 'self'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cross-Origin-Embedder-Policy": "require-corp",
}


@app.after_request
def set_security_headers(response: Response) -> Response:
    response.headers.update(SECURITY_HEADERS)
    return response


@app.after_request
def protokolliere_anfrage(response: Response) -> Response:
    benutzer = g.get("user")
    protokolliere(
        "request",
        method=request.method,
        path=request.path,
        status=response.status_code,
        user_id=benutzer["id"] if benutzer else session.get("user_id"),
    )
    return response


# ---------------------------------------------------------------------------
# Datenbank & Initialisierung
# ---------------------------------------------------------------------------


def hash_passwort(passwort: str) -> str:
    """Gesalzener, absichtlich langsamer Hash (scrypt), kein eigenes Verfahren."""
    return generate_password_hash(passwort)


# Vergleichswert für unbekannte Benutzer: Der Login dauert dann genauso lange wie bei
# einem falschen Passwort und verrät nicht über die Laufzeit, ob es den Namen gibt.
DUMMY_HASH = hash_passwort(secrets.token_urlsafe(16))


def neues_token() -> str:
    """Kryptografisch zufälliges API-Token mit erkennbarem Präfix (für Secret Scanner)."""
    return "gt_" + secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """In der Datenbank steht nur der Hash. Ein Datenbank-Leak verrät keine gültigen Tokens."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return cast(sqlite3.Connection, g.db)


@app.teardown_appcontext
def close_db(e: BaseException | None = None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    db = get_db()
    db.executescript(SCHEMA_SQL)
    if DEMO_DATA:
        lade_demodaten(db)
    db.commit()


@functools.cache
def demo_hash(passwort: str) -> str:
    # scrypt ist absichtlich langsam. Die Demo-Hashes werden pro Prozess nur einmal berechnet,
    # sonst dauert jedes Zurücksetzen der Datenbank (z. B. in den Tests) spürbar länger.
    return hash_passwort(passwort)


def lade_demodaten(db: sqlite3.Connection) -> None:
    db.executemany(
        "INSERT INTO users (username, full_name, password_hash, role, api_token) VALUES (?, ?, ?, ?, ?)",
        [
            (name, voller_name, demo_hash(passwort), rolle, token_hash(neues_token()))
            for name, voller_name, passwort, rolle in [
                ("pamt", "Prüfungsamt DHBW", "admin123", "registrar"),
                ("tobias", "Tobias Gehrke", "tobias123", "student"),
                ("pavel", "Pavel Kullmann", "pavel123", "student"),
                ("anastasia", "Anastasia Rotermel", "anastasia123", "student"),
            ]
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


# ---------------------------------------------------------------------------
# Authentifizierung & Rollen
# ---------------------------------------------------------------------------


def get_token() -> str | None:
    # Nur im Header. Tokens in der URL landen in Server-Logs, im Browserverlauf und im Referer.
    return request.headers.get("X-API-Token")


def load_user() -> Zeile | None:
    if "user_id" in session:
        row = get_db().execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        if row is not None:
            return dict(row)

    token = get_token()
    if not token:
        return None

    row = get_db().execute("SELECT * FROM users WHERE api_token = ?", (token_hash(token),)).fetchone()
    if row is None:
        return None
    return dict(row)


# Eine Meldung für unbekannte Namen und falsche Passwörter (keine User Enumeration).
LOGIN_FEHLER = "Benutzername oder Passwort falsch"


def authenticate_credentials(username: str, password: str) -> Zeile | None:
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    # Eine Meldung für beide Fälle, sonst ließe sich ausprobieren, welche Namen existieren.
    gespeichert = row["password_hash"] if row is not None else DUMMY_HASH
    if not check_password_hash(gespeichert, password) or row is None:
        # Name (geprüft, max. 64 Zeichen, JSON-kodiert) ja, Passwort nie.
        protokolliere("login_failed", logging.WARNING, username=username)
        return None

    protokolliere("login_ok", user_id=row["id"])
    return dict(row)


def login_required(view: View) -> View:
    @functools.wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> ResponseReturnValue:
        user = load_user()
        if user is None:
            return jsonify({"error": "Nicht angemeldet"}), 401
        g.user = user
        return view(*args, **kwargs)

    return wrapped


def registrar_required(view: View) -> View:
    @functools.wraps(view)
    @login_required
    def wrapped(*args: Any, **kwargs: Any) -> ResponseReturnValue:
        if g.user["role"] != "registrar":
            return jsonify({"error": "Nur für das Prüfungsamt"}), 403
        return view(*args, **kwargs)

    return wrapped


# ---------------------------------------------------------------------------
# Eingabeprüfung (Fail Fast)
# ---------------------------------------------------------------------------


class UngueltigeEingabe(Exception):
    """Eingabe verletzt das Schema oder eine Fachregel. Wird zentral mit 400 beantwortet."""

    def __init__(self, meldung: str, details: list[dict[str, str]] | None = None) -> None:
        super().__init__(meldung)
        self.meldung = meldung
        self.details = details or []


def fehlerliste(fehler: ValidationError) -> list[dict[str, str]]:
    # Nur Feld und Regel, nie den Eingabewert selbst: Die Antwort spiegelt nichts zurück.
    return [
        {"feld": ".".join(str(teil) for teil in e["loc"]) or "eingabe", "meldung": e["msg"]}
        for e in fehler.errors(include_url=False, include_input=False, include_context=False)
    ]


def pruefe[M: BaseModel](modell: type[M], daten: Mapping[str, Any], strict: bool = True) -> M:
    try:
        return modell.model_validate(daten, strict=strict)
    except ValidationError as fehler:
        raise UngueltigeEingabe("Ungültige Eingabe", fehlerliste(fehler)) from None


def json_eingabe[M: BaseModel](modell: type[M]) -> M:
    """JSON-Body gegen ein Schema prüfen. Typen müssen exakt passen ("5" ist keine Zahl)."""
    if not request.is_json:
        raise UnsupportedMediaType("Content-Type muss application/json sein")
    try:
        return modell.model_validate_json(request.get_data())
    except ValidationError as fehler:
        raise UngueltigeEingabe("Ungültige Eingabe", fehlerliste(fehler)) from None


def parameter_eingabe[M: BaseModel](
    modell: type[M], quelle: Mapping[str, str], auslassen: tuple[str, ...] = ("csrf_token",)
) -> M:
    """URL-Parameter und Formularfelder prüfen. Sie sind immer Text, leere Felder gelten als nicht gesetzt."""
    daten = {k: v for k, v in quelle.items() if v != "" and k not in auslassen}
    return pruefe(modell, daten, strict=False)


def pruefe_modul_existiert(code: str) -> None:
    if get_db().execute("SELECT 1 FROM modules WHERE code = ?", (code,)).fetchone() is None:
        raise UngueltigeEingabe("Ungültige Eingabe", [{"feld": "module_code", "meldung": "Modul existiert nicht"}])


def pruefe_ist_student(student_id: int) -> None:
    zeile = get_db().execute("SELECT role FROM users WHERE id = ?", (student_id,)).fetchone()
    if zeile is None or zeile["role"] != "student":
        raise UngueltigeEingabe(
            "Ungültige Eingabe", [{"feld": "student_id", "meldung": "Keine Studierende/r mit dieser ID"}]
        )


def als_text(datum: date | None) -> str | None:
    return datum.isoformat() if datum is not None else None


def flash_fehler(fehler: UngueltigeEingabe) -> None:
    details = "; ".join(f"{d['feld']}: {d['meldung']}" for d in fehler.details)
    flash(f"{fehler.meldung}: {details}" if details else fehler.meldung, "error")


@app.errorhandler(UngueltigeEingabe)
def ungueltige_eingabe(fehler: UngueltigeEingabe) -> ResponseReturnValue:
    return jsonify({"error": fehler.meldung, "details": fehler.details}), 400


# ---------------------------------------------------------------------------
# Rechte pro Objekt und sichere Abfragen
# ---------------------------------------------------------------------------

# Feste Zuordnung Sortierwunsch -> SQL. Spaltennamen kommen nie aus der Anfrage.
SORTIERUNG_SQL = {
    "id": "id",
    "semester": "semester, id",
    "grade": "grade, id",
    "module_code": "module_code, id",
    "exam_date": "exam_date, id",
    "status": "status, id",
}


def ist_pruefungsamt(user: Zeile) -> bool:
    return bool(user["role"] == "registrar")


def sichtbare_note(note_id: int, user: Zeile) -> Zeile | None:
    """Liefert die Note, wenn die Person sie sehen darf, sonst None.

    Studierende sehen nur eigene Noten. Fremde Noten werden wie nicht vorhandene behandelt
    (404 statt 403), damit sich nicht ausprobieren lässt, welche IDs es gibt.
    """
    zeile = get_db().execute("SELECT * FROM grades WHERE id = ?", (note_id,)).fetchone()
    if zeile is None:
        return None
    if not ist_pruefungsamt(user) and zeile["student_id"] != user["id"]:
        return None
    return dict(zeile)


def ziel_student(student_id: int | None, user: Zeile) -> int:
    """Studierende tragen nur für sich selbst ein, das Prüfungsamt für eine/n Studierende/n."""
    if ist_pruefungsamt(user):
        if student_id is None:
            raise UngueltigeEingabe("Ungültige Eingabe", [{"feld": "student_id", "meldung": "Pflichtfeld für das Prüfungsamt"}])
        pruefe_ist_student(student_id)
        return student_id
    if student_id is not None and student_id != user["id"]:
        raise UngueltigeEingabe("Ungültige Eingabe", [{"feld": "student_id", "meldung": "Nur für sich selbst"}])
    return int(user["id"])


def like_muster(text: str) -> str:
    """Suchtext für LIKE: % und _ gelten als normale Zeichen, nicht als Platzhalter."""
    maskiert = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{maskiert}%"


# ---------------------------------------------------------------------------
# Web-Oberfläche (Browser UI)
# ---------------------------------------------------------------------------


@app.get("/login")
def login_page() -> ResponseReturnValue:
    if load_user():
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.post("/login")
def login_submit() -> ResponseReturnValue:
    try:
        eingabe = parameter_eingabe(schemas.LoginEingabe, request.form)
    except UngueltigeEingabe:
        flash(LOGIN_FEHLER, "error")
        return redirect(url_for("login_page"))

    user = authenticate_credentials(eingabe.username, eingabe.password)
    if user is None:
        flash(LOGIN_FEHLER, "error")
        return redirect(url_for("login_page"))

    session["user_id"] = user["id"]
    flash(f"Willkommen zurück, {user['full_name']}!", "success")
    return redirect(url_for("dashboard"))


@app.get("/logout")
def logout() -> ResponseReturnValue:
    session.clear()
    flash("Du wurdest abgemeldet.", "info")
    return redirect(url_for("login_page"))


@app.get("/")
def dashboard() -> ResponseReturnValue:
    user = load_user()
    if not user:
        return redirect(url_for("login_page"))

    db = get_db()
    try:
        filter_ = parameter_eingabe(schemas.DashboardFilter, request.args)
    except UngueltigeEingabe:
        flash("Ungültiger Filter, es werden alle Einträge angezeigt.", "error")
        filter_ = schemas.DashboardFilter()
    semester = filter_.semester
    status = filter_.status
    search = filter_.search or ""

    if ist_pruefungsamt(user):
        selected_student_id = filter_.student_id
    else:
        # Studierende sehen immer nur ihre eigenen Noten, egal was in der URL steht.
        selected_student_id = user["id"]

    query = (
        "SELECT g.*, u.username AS student_name, u.full_name AS student_full_name, m.title AS module_title "
        "FROM grades g "
        "LEFT JOIN users u ON g.student_id = u.id "
        "LEFT JOIN modules m ON g.module_code = m.code "
        "WHERE 1=1"
    )
    params: list[object] = []
    if semester:
        query += " AND g.semester = ?"
        params.append(semester)
    if selected_student_id:
        query += " AND g.student_id = ?"
        params.append(selected_student_id)
    if status:
        query += " AND g.status = ?"
        params.append(status)
    query += " ORDER BY g.semester, g.id"

    grades = [dict(r) for r in db.execute(query, params).fetchall()]

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
    mod_params: list[object] = []
    if search:
        mod_query += " WHERE title LIKE ? ESCAPE '\\' OR code LIKE ? ESCAPE '\\'"
        mod_params = [like_muster(search), like_muster(search)]
    modules = [dict(r) for r in db.execute(mod_query, mod_params).fetchall()]

    students = (
        [dict(r) for r in db.execute("SELECT id, username, full_name, role FROM users").fetchall()]
        if ist_pruefungsamt(user)
        else []
    )

    full_name = user.get("full_name") or user.get("username", "U")
    parts = full_name.split()
    initials = (parts[0][0] + (parts[1][0] if len(parts) > 1 else parts[0][1:2])).upper()

    tab = filter_.tab
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
            "semester": str(semester) if semester else "",
            "status": status or "",
            "student_id": str(selected_student_id) if selected_student_id else "",
            "search": search,
        },
    )


@app.post("/ui/grades/add")
def ui_add_grade() -> ResponseReturnValue:
    user = load_user()
    if not user:
        return redirect(url_for("login_page"))

    try:
        note = parameter_eingabe(schemas.NoteNeu, request.form)
        pruefe_modul_existiert(note.module_code)
        student_id = ziel_student(note.student_id, user)
    except UngueltigeEingabe as fehler:
        flash_fehler(fehler)
        return redirect(url_for("dashboard", tab="add"))

    db = get_db()
    db.execute(
        "INSERT INTO grades (student_id, module_code, grade, ects, semester, exam_date, attempt, comment, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
        (
            student_id,
            note.module_code,
            note.grade,
            note.ects,
            note.semester,
            als_text(note.exam_date),
            note.attempt,
            note.comment,
        ),
    )
    db.commit()
    flash(f"Prüfung {note.module_code} (Note {note.grade}) wurde eingetragen.", "success")
    return redirect(url_for("dashboard", tab="overview"))


@app.post("/ui/grades/<int:grade_id>/approve")
def ui_approve_grade(grade_id: int) -> ResponseReturnValue:
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
def ui_delete_grade(grade_id: int) -> ResponseReturnValue:
    user = load_user()
    if not user or user["role"] != "registrar":
        flash("Nur das Prüfungsamt darf Noten löschen!", "error")
        return redirect(url_for("dashboard"))

    db = get_db()
    cur = db.execute("DELETE FROM grades WHERE id = ?", (grade_id,))
    db.commit()
    if cur.rowcount == 0:
        flash(f"Note #{grade_id} gibt es nicht.", "error")
    else:
        flash(f"Note #{grade_id} wurde gelöscht.", "info")
    return redirect(url_for("dashboard"))


@app.post("/ui/modules/add")
def ui_add_module() -> ResponseReturnValue:
    user = load_user()
    if not user:
        return redirect(url_for("login_page"))
    if not ist_pruefungsamt(user):
        flash("Nur das Prüfungsamt darf Module anlegen!", "error")
        return redirect(url_for("dashboard", tab="modules"))

    try:
        modul = parameter_eingabe(schemas.ModulNeu, request.form)
    except UngueltigeEingabe as fehler:
        flash_fehler(fehler)
        return redirect(url_for("dashboard", tab="modules"))

    db = get_db()
    try:
        db.execute(
            "INSERT INTO modules (code, title, ects, semester) VALUES (?, ?, ?, ?)",
            (modul.code, modul.title, modul.ects, modul.semester),
        )
    except sqlite3.IntegrityError:
        flash(f"Modul {modul.code} gibt es bereits.", "error")
        return redirect(url_for("dashboard", tab="modules"))
    db.commit()
    flash(f"Modul {modul.code} angelegt.", "success")
    return redirect(url_for("dashboard", tab="modules"))


@app.post("/ui/users/add")
def ui_add_user() -> ResponseReturnValue:
    user = load_user()
    if not user or user["role"] != "registrar":
        flash("Nur das Prüfungsamt darf Benutzer anlegen!", "error")
        return redirect(url_for("dashboard"))

    try:
        neu = parameter_eingabe(schemas.BenutzerNeu, request.form)
    except UngueltigeEingabe as fehler:
        flash_fehler(fehler)
        return redirect(url_for("dashboard", tab="users"))
    username, password, role = neu.username, neu.password, neu.role
    full_name = neu.full_name or username

    db = get_db()
    try:
        db.execute(
            "INSERT INTO users (username, full_name, password_hash, role, api_token) VALUES (?, ?, ?, ?, ?)",
            (username, full_name, hash_passwort(password), role, token_hash(neues_token())),
        )
    except sqlite3.IntegrityError:
        flash(f"Benutzername '{username}' ist bereits vergeben.", "error")
        return redirect(url_for("dashboard", tab="users"))
    db.commit()
    flash(f"Benutzer '{full_name}' ({username}) angelegt.", "success")
    return redirect(url_for("dashboard", tab="users"))


# ---------------------------------------------------------------------------
# REST-API Endpunkte (JSON)
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> ResponseReturnValue:
    return jsonify({"status": "ok"})


@app.post("/auth/login")
@ohne_csrf
def api_login() -> ResponseReturnValue:
    eingabe = json_eingabe(schemas.LoginEingabe)
    user = authenticate_credentials(eingabe.username, eingabe.password)
    if user is None:
        return jsonify({"error": LOGIN_FEHLER}), 401

    # Jeder API-Login stellt ein neues Token aus und macht das alte ungültig. Gespeichert
    # wird nur der Hash, das Token selbst sieht der Client genau einmal.
    token = neues_token()
    db = get_db()
    db.execute("UPDATE users SET api_token = ? WHERE id = ?", (token_hash(token), user["id"]))
    db.commit()

    session["user_id"] = user["id"]
    return jsonify(
        {
            "id": user["id"],
            "username": user["username"],
            "full_name": user["full_name"],
            "role": user["role"],
            "api_token": token,
        }
    )


@app.post("/auth/logout")
@ohne_csrf
def api_logout() -> ResponseReturnValue:
    session.clear()
    return jsonify({"message": "Abgemeldet"})


@app.get("/grades")
@login_required
def list_grades() -> ResponseReturnValue:
    filter_ = parameter_eingabe(schemas.NotenFilter, request.args)
    student_id = filter_.student_id
    if not ist_pruefungsamt(g.user):
        if student_id is not None and student_id != g.user["id"]:
            return jsonify({"error": "Nur eigene Noten"}), 403
        student_id = g.user["id"]

    # Alle Werte als Parameter (?). Die Abfrage selbst besteht nur aus festen Bausteinen.
    query = "SELECT * FROM grades WHERE 1=1"
    params: list[object] = []
    if filter_.semester is not None:
        query += " AND semester = ?"
        params.append(filter_.semester)
    if student_id is not None:
        query += " AND student_id = ?"
        params.append(student_id)
    if filter_.status is not None:
        query += " AND status = ?"
        params.append(filter_.status)
    query += " ORDER BY " + SORTIERUNG_SQL[filter_.sort]

    rows = get_db().execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/grades/<int:grade_id>")
@login_required
def get_grade(grade_id: int) -> ResponseReturnValue:
    note = sichtbare_note(grade_id, g.user)
    if note is None:
        return jsonify({"error": "Note nicht gefunden"}), 404
    return jsonify(note)


@app.post("/grades")
@ohne_csrf
@login_required
def create_grade() -> ResponseReturnValue:
    note = json_eingabe(schemas.NoteNeu)
    pruefe_modul_existiert(note.module_code)
    student_id = ziel_student(note.student_id, g.user)

    db = get_db()
    cur = db.execute(
        "INSERT INTO grades (student_id, module_code, grade, ects, semester, exam_date, attempt, comment, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
        (
            student_id,
            note.module_code,
            note.grade,
            note.ects,
            note.semester,
            als_text(note.exam_date),
            note.attempt,
            note.comment,
        ),
    )
    db.commit()
    protokolliere("grade_created", user_id=g.user["id"], grade_id=cur.lastrowid, student_id=student_id)

    row = db.execute("SELECT * FROM grades WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201


@app.put("/grades/<int:grade_id>")
@ohne_csrf
@login_required
def update_grade(grade_id: int) -> ResponseReturnValue:
    note = sichtbare_note(grade_id, g.user)
    if note is None:
        return jsonify({"error": "Note nicht gefunden"}), 404
    if note["status"] == "approved" and not ist_pruefungsamt(g.user):
        return jsonify({"error": "Bestätigte Noten kann nur das Prüfungsamt ändern"}), 403

    aenderung = json_eingabe(schemas.NoteAenderung)
    if aenderung.module_code is not None:
        pruefe_modul_existiert(aenderung.module_code)

    # Feste Anweisung: Nicht gesetzte Felder (NULL) behalten ihren Wert.
    db = get_db()
    db.execute(
        "UPDATE grades SET module_code = COALESCE(?, module_code), grade = COALESCE(?, grade), "
        "ects = COALESCE(?, ects), semester = COALESCE(?, semester), exam_date = COALESCE(?, exam_date), "
        "attempt = COALESCE(?, attempt), comment = COALESCE(?, comment) WHERE id = ?",
        (
            aenderung.module_code,
            aenderung.grade,
            aenderung.ects,
            aenderung.semester,
            als_text(aenderung.exam_date),
            aenderung.attempt,
            aenderung.comment,
            grade_id,
        ),
    )
    db.commit()

    row = db.execute("SELECT * FROM grades WHERE id = ?", (grade_id,)).fetchone()
    return jsonify(dict(row))


@app.post("/grades/<int:grade_id>/approve")
@ohne_csrf
@registrar_required
def approve_grade(grade_id: int) -> ResponseReturnValue:
    db = get_db()
    cur = db.execute(
        "UPDATE grades SET status = 'approved', approved_by = ?, approved_at = ? WHERE id = ?",
        (g.user["id"], datetime.now().isoformat(), grade_id),
    )
    db.commit()
    if cur.rowcount == 0:
        return jsonify({"error": "Note nicht gefunden"}), 404
    protokolliere("grade_approved", user_id=g.user["id"], grade_id=grade_id)
    return jsonify({"message": f"Note {grade_id} bestätigt"})


@app.delete("/grades/<int:grade_id>")
@ohne_csrf
@registrar_required
def delete_grade(grade_id: int) -> ResponseReturnValue:
    db = get_db()
    cur = db.execute("DELETE FROM grades WHERE id = ?", (grade_id,))
    db.commit()
    if cur.rowcount == 0:
        return jsonify({"error": "Note nicht gefunden"}), 404
    return jsonify({"message": f"Note {grade_id} gelöscht"})


@app.get("/modules")
def list_modules() -> ResponseReturnValue:
    search = parameter_eingabe(schemas.ModulSuche, request.args).search
    query = "SELECT * FROM modules"
    params: list[object] = []
    if search:
        query += " WHERE title LIKE ? ESCAPE '\\' OR code LIKE ? ESCAPE '\\'"
        params = [like_muster(search), like_muster(search)]
    rows = get_db().execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/modules")
@ohne_csrf
@registrar_required
def create_module() -> ResponseReturnValue:
    modul = json_eingabe(schemas.ModulNeu)
    db = get_db()
    try:
        db.execute(
            "INSERT INTO modules (code, title, ects, semester) VALUES (?, ?, ?, ?)",
            (modul.code, modul.title, modul.ects, modul.semester),
        )
    except sqlite3.IntegrityError:
        raise UngueltigeEingabe("Ungültige Eingabe", [{"feld": "code", "meldung": "Modul gibt es bereits"}]) from None
    db.commit()
    return jsonify(modul.model_dump()), 201


@app.get("/stats/ects")
@login_required
def ects_stats() -> ResponseReturnValue:
    filter_ = parameter_eingabe(schemas.StatistikFilter, request.args)
    student_id = filter_.student_id or g.user["id"]
    if not ist_pruefungsamt(g.user) and student_id != g.user["id"]:
        return jsonify({"error": "Nur eigene Statistik"}), 403
    semester = filter_.semester

    query = "SELECT grade, ects FROM grades WHERE student_id = ?"
    params: list[object] = [student_id]
    if semester:
        query += " AND semester = ?"
        params.append(semester)

    rows = get_db().execute(query, params).fetchall()

    passed = [r for r in rows if r["grade"] <= 4.0]
    total_ects = sum(r["ects"] for r in passed)
    # Ohne bestandene Prüfungen gibt es keinen Durchschnitt (statt Division durch null).
    average = round(sum(r["grade"] * r["ects"] for r in passed) / total_ects, 2) if total_ects else None

    return jsonify(
        {
            "student_id": student_id,
            "semester": semester,
            "exams": len(rows),
            "passed": len(passed),
            "failed": len(rows) - len(passed),
            "total_ects": total_ects,
            "average": average,
        }
    )


@app.get("/users")
@registrar_required
def list_users() -> ResponseReturnValue:
    rows = get_db().execute("SELECT id, username, full_name, role FROM users").fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/users")
@ohne_csrf
@registrar_required
def create_user() -> ResponseReturnValue:
    neu = json_eingabe(schemas.BenutzerNeu)
    full_name = neu.full_name or neu.username
    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO users (username, full_name, password_hash, role, api_token) VALUES (?, ?, ?, ?, ?)",
            (neu.username, full_name, hash_passwort(neu.password), neu.role, token_hash(neues_token())),
        )
    except sqlite3.IntegrityError:
        raise UngueltigeEingabe(
            "Ungültige Eingabe", [{"feld": "username", "meldung": "Benutzername ist bereits vergeben"}]
        ) from None
    db.commit()
    protokolliere("user_created", user_id=g.user["id"], new_user_id=cur.lastrowid, role=neu.role)
    # Kein Token in der Antwort: Die Person holt sich ihr eigenes beim ersten Login.
    return jsonify({"id": cur.lastrowid, "username": neu.username, "full_name": full_name}), 201


@app.errorhandler(Exception)
def handle_error(e: Exception) -> ResponseReturnValue:
    if isinstance(e, HTTPException):
        return jsonify({"error": e.description}), e.code or 500
    # Stacktrace, Fehlertyp und Pfade verraten Interna. Sie gehen nur ins Log,
    # die Antwort enthält eine ID, über die sich der Eintrag dort finden lässt.
    fehler_id = uuid.uuid4().hex[:12]
    log.error("internal_error", exc_info=e, extra={"felder": {"error_id": fehler_id, "path": request.path}})
    return jsonify({"error": "Interner Fehler", "error_id": fehler_id}), 500


def lege_pruefungsamt_an(username: str) -> None:
    """Legt einen Prüfungsamt-Zugang an. Das Passwort wird verdeckt abgefragt."""
    passwort = getpass.getpass(f"Passwort für {username} (mind. 12 Zeichen): ")
    if len(passwort) < 12:
        raise SystemExit("[Fehler] Das Passwort muss mindestens 12 Zeichen lang sein.")
    if getpass.getpass("Passwort wiederholen: ") != passwort:
        raise SystemExit("[Fehler] Die Passwörter stimmen nicht überein.")
    db = get_db()
    try:
        db.execute(
            "INSERT INTO users (username, full_name, password_hash, role, api_token) VALUES (?, ?, ?, ?, ?)",
            (username, "Prüfungsamt", hash_passwort(passwort), "registrar", token_hash(neues_token())),
        )
    except sqlite3.IntegrityError:
        raise SystemExit(f"[Fehler] Benutzer {username!r} existiert bereits.") from None
    db.commit()


with app.app_context():
    if not os.path.exists(app.config["DATABASE"]):
        init_db()
        protokolliere("database_created", demo_data=DEMO_DATA)
        if not DEMO_DATA:
            print("[db] Ohne Beispieldaten angelegt. Zugang anlegen: python gradetrack.py --create-registrar <name>")


if __name__ == "__main__":
    if "--init-db" in sys.argv:
        with app.app_context():
            init_db()
            print("Datenbank frisch initialisiert" + (" (mit Beispieldaten)." if DEMO_DATA else " (leer)."))
    elif "--create-registrar" in sys.argv:
        position = sys.argv.index("--create-registrar")
        if position + 1 >= len(sys.argv):
            raise SystemExit("Aufruf: python gradetrack.py --create-registrar <benutzername>")
        with app.app_context():
            lege_pruefungsamt_an(sys.argv[position + 1])
            print("Zugang angelegt.")
    else:
        app.run(host=HOST, port=PORT, debug=DEBUG)
