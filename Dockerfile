# GradeTrack als Container-Image
#
# Base-Image per Digest gepinnt: Der Tag nennt die Version für Menschen,
# der Digest legt das Image unveränderlich fest (scripts/check-pinning.sh prüft das).
FROM python:3.14.10-slim-trixie@sha256:22eafb370920ad8b429e0aec3fff433e0669968519f5d60469d83729c138b28b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    GRADETRACK_DB=/data/grades.db

WORKDIR /app

# Nur genau die Versionen aus dem Lock-File, jede Datei wird gegen ihren Hash geprüft.
COPY requirements.txt .
RUN pip install --require-hashes --no-deps -r requirements.txt

# Eigener Benutzer ohne Root-Rechte und ohne Login-Shell.
# Nur /data ist für ihn beschreibbar, der Code in /app gehört root.
RUN groupadd --system --gid 10001 gradetrack \
 && useradd --system --uid 10001 --gid gradetrack --no-create-home --shell /usr/sbin/nologin gradetrack \
 && mkdir /data \
 && chown gradetrack:gradetrack /data

COPY gradetrack.py schemas.py ./
COPY templates/ templates/
COPY static/ static/

USER gradetrack

VOLUME ["/data"]
EXPOSE 8000

# gunicorn statt Flask-Entwicklungsserver. Ein Worker, weil die App beim Start
# die SQLite-Datenbank anlegt; mehrere Threads reichen für die Last.
# --no-control-socket: Die Fernsteuer-Schnittstelle von gunicorn brauchen wir nicht
# (weniger Angriffsfläche, und der Benutzer hat bewusst kein Home-Verzeichnis).
# --preload: Die App wird einmal im Hauptprozess geladen. Fehlt z. B. GRADETRACK_SECRET_KEY,
# beendet sich der Container sofort, statt den Worker endlos neu zu starten.
# Kein gunicorn-Zugriffsprotokoll: Es schreibt die ganze URL samt Query-String (dort könnten
# Suchtexte oder fälschlich mitgeschickte Tokens stehen). Die App protokolliert jede Anfrage
# selbst als JSON-Zeile, ohne Query-String.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--no-control-socket", "--preload", "gradetrack:app"]
