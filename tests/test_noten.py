import pytest

TOBIAS_ID = 2

NEUE_NOTE = {"module_code": "INF-2001", "grade": 2.7, "ects": 5, "semester": 2}


def test_student_sieht_eigene_noten(student):
    antwort = student.get("/grades")

    assert antwort.status_code == 200
    eigene = [n for n in antwort.get_json() if n["student_id"] == TOBIAS_ID]
    assert {n["module_code"] for n in eigene} == {"INF-1001", "INF-1002", "INF-3002"}


def test_student_traegt_note_ein(student):
    antwort = student.post("/grades", json=NEUE_NOTE)

    assert antwort.status_code == 201
    note = antwort.get_json()
    assert note["student_id"] == TOBIAS_ID
    assert note["grade"] == 2.7
    assert note["status"] == "pending"
    assert student.get(f"/grades/{note['id']}").get_json()["module_code"] == "INF-2001"


@pytest.mark.parametrize("ungueltige_note", [0.7, 5.3])
def test_note_ausserhalb_von_1_bis_5_wird_abgelehnt(student, ungueltige_note):
    antwort = student.post("/grades", json={**NEUE_NOTE, "grade": ungueltige_note})

    assert antwort.status_code == 400


def test_unbekannte_note_liefert_404(student):
    assert student.get("/grades/9999").status_code == 404


def test_pruefungsamt_aendert_kommentar(pruefungsamt):
    antwort = pruefungsamt.put("/grades/3", json={"comment": "Nachgereicht"})

    assert antwort.status_code == 200
    assert antwort.get_json()["comment"] == "Nachgereicht"


def test_modulliste_enthaelt_alle_module(client):
    antwort = client.get("/modules")

    assert antwort.status_code == 200
    assert len(antwort.get_json()) == 5


def test_modulsuche_findet_passendes_modul(client):
    antwort = client.get("/modules", query_string={"search": "Datenbank"})

    assert [m["code"] for m in antwort.get_json()] == ["INF-2001"]


def test_pruefungsamt_legt_modul_an(pruefungsamt):
    neues_modul = {"code": "INF-4001", "title": "Verteilte Systeme", "ects": 5, "semester": 4}

    antwort = pruefungsamt.post("/modules", json=neues_modul)

    assert antwort.status_code == 201
    assert "INF-4001" in [m["code"] for m in pruefungsamt.get("/modules").get_json()]


def test_ects_statistik_fuer_eigene_noten(student):
    antwort = student.get("/stats/ects")

    assert antwort.status_code == 200
    statistik = antwort.get_json()
    assert statistik["exams"] == 3
    assert statistik["passed"] == 3
    assert statistik["total_ects"] == 18
    assert statistik["average"] == 1.72


def test_ects_statistik_fuer_ein_semester(student):
    statistik = student.get("/stats/ects", query_string={"semester": 1}).get_json()

    assert statistik["exams"] == 2
    assert statistik["total_ects"] == 13
    assert statistik["average"] == 1.88
