import os
import sqlite3


def test_health_meldet_ok_bei_erreichbarer_datenbank(client):
    antwort = client.get("/health")

    assert antwort.status_code == 200
    assert antwort.get_json() == {"status": "ok", "checks": {"database": "ok"}}


def test_health_meldet_fehler_ohne_datenbankdatei(app, client):
    os.remove(app.config["DATABASE"])

    antwort = client.get("/health")

    assert antwort.status_code == 503
    assert antwort.get_json() == {"status": "error", "checks": {"database": "error"}}
    assert not os.path.exists(app.config["DATABASE"])


def test_health_meldet_fehler_bei_unvollstaendigem_schema(app, client):
    with sqlite3.connect(app.config["DATABASE"]) as verbindung:
        verbindung.execute("DROP TABLE grades")

    antwort = client.get("/health")

    assert antwort.status_code == 503
    assert antwort.get_json()["checks"]["database"] == "error"


def test_health_verraet_keine_interna(app, client):
    os.remove(app.config["DATABASE"])

    antwort = client.get("/health")

    text = antwort.get_data(as_text=True)
    assert "sqlite" not in text.lower()
    assert app.config["DATABASE"] not in text
