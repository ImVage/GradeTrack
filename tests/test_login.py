def test_login_seite_wird_angezeigt(client):
    antwort = client.get("/login")

    assert antwort.status_code == 200
    assert b'id="loginForm"' in antwort.data


def test_testdatenbank_enthaelt_beispielbenutzer(app, tmp_path):
    from gradetrack import get_db

    assert app.config["DATABASE"] == str(tmp_path / "grades.db")
    with app.app_context():
        namen = {zeile["username"] for zeile in get_db().execute("SELECT username FROM users")}

    assert namen == {"pamt", "tobias", "pavel", "anastasia"}
