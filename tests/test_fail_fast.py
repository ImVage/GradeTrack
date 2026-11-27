"""Fail-Fast-Tests für Feld 2 (Code Security).

Ungültige Eingaben müssen sofort mit 400 und einer klaren Meldung abgelehnt werden, statt
gespeichert, "repariert" oder erst später als Serverfehler (500) aufzufallen.

Am unsicheren Ausgangsstand schlagen diese Tests fehl (Positivtest), nach den Fixes müssen
sie grün sein und bleiben.
"""

import re

import pytest

NEUE_NOTE = {"module_code": "INF-2001", "grade": 2.7, "ects": 5, "semester": 2}


@pytest.mark.parametrize(
    "aenderung",
    [
        pytest.param({"grade": "abc"}, id="note-kein-zahlwert"),
        pytest.param({"ects": "5"}, id="ects-als-text"),
        pytest.param({"semester": 99}, id="semester-ausserhalb"),
        pytest.param({"ects": -5}, id="ects-negativ"),
        pytest.param({"module_code": "inf 2001; --"}, id="modulcode-falsches-format"),
        pytest.param({"module_code": "XYZ-9999"}, id="modul-existiert-nicht"),
        pytest.param({"comment": "x" * 5000}, id="kommentar-zu-lang"),
        pytest.param({"unbekannt": 1}, id="unbekanntes-feld"),
    ],
)
def test_ungueltige_note_wird_mit_400_abgelehnt(student, aenderung):
    antwort = student.post("/grades", json={**NEUE_NOTE, **aenderung})

    assert antwort.status_code == 400
    assert "error" in antwort.get_json()


def test_fehlendes_pflichtfeld_wird_mit_400_abgelehnt(student):
    daten = {k: v for k, v in NEUE_NOTE.items() if k != "module_code"}

    antwort = student.post("/grades", json=daten)

    assert antwort.status_code == 400


@pytest.mark.parametrize("body", ["null", "[1, 2]", '"text"'])
def test_json_ohne_objekt_wird_mit_400_abgelehnt(student, body):
    antwort = student.post("/grades", data=body, content_type="application/json")

    assert antwort.status_code == 400


@pytest.mark.parametrize(
    "parameter",
    [
        pytest.param("semester=abc", id="semester-kein-zahlwert"),
        pytest.param("status=geheim", id="status-nicht-erlaubt"),
        pytest.param("sort=password_hash", id="sortierung-nicht-erlaubt"),
    ],
)
def test_ungueltige_filter_werden_mit_400_abgelehnt(student, parameter):
    antwort = student.get(f"/grades?{parameter}")

    assert antwort.status_code == 400


def test_ungueltige_note_im_formular_fuehrt_nicht_zu_serverfehler(student):
    seite = student.get("/").get_data(as_text=True)
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', seite).group(1)

    antwort = student.post(
        "/ui/grades/add",
        data={"module_code": "INF-2001", "grade": "abc", "ects": "5", "semester": "2", "csrf_token": csrf},
    )

    assert antwort.status_code in (302, 400)
