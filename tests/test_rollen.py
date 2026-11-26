OFFENE_NOTE_ID = 3


def test_student_darf_note_nicht_bestaetigen(student):
    antwort = student.post(f"/grades/{OFFENE_NOTE_ID}/approve")

    assert antwort.status_code == 403
    assert student.get(f"/grades/{OFFENE_NOTE_ID}").get_json()["status"] == "pending"


def test_student_darf_note_nicht_loeschen(student):
    antwort = student.delete(f"/grades/{OFFENE_NOTE_ID}")

    assert antwort.status_code == 403
    assert student.get(f"/grades/{OFFENE_NOTE_ID}").status_code == 200


def test_student_darf_keinen_benutzer_anlegen(student):
    antwort = student.post("/users", json={"username": "neu", "password": "Sicher-genug-123"})

    assert antwort.status_code == 403


def test_pruefungsamt_bestaetigt_note(pruefungsamt):
    antwort = pruefungsamt.post(f"/grades/{OFFENE_NOTE_ID}/approve")

    assert antwort.status_code == 200
    note = pruefungsamt.get(f"/grades/{OFFENE_NOTE_ID}").get_json()
    assert note["status"] == "approved"
    assert note["approved_at"] is not None


def test_pruefungsamt_loescht_note(pruefungsamt):
    antwort = pruefungsamt.delete(f"/grades/{OFFENE_NOTE_ID}")

    assert antwort.status_code == 200
    assert pruefungsamt.get(f"/grades/{OFFENE_NOTE_ID}").status_code == 404


def test_pruefungsamt_legt_benutzer_an(pruefungsamt):
    antwort = pruefungsamt.post(
        "/users", json={"username": "neu", "full_name": "Neue Person", "password": "Sicher-genug-123"}
    )

    assert antwort.status_code == 201
    assert antwort.get_json()["username"] == "neu"
