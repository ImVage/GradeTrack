def test_web_login_mit_richtigen_daten_fuehrt_zum_dashboard(client, zugangsdaten):
    benutzername, passwort = zugangsdaten["student"]

    antwort = client.post("/login", data={"username": benutzername, "password": passwort})

    assert antwort.status_code == 302
    assert antwort.headers["Location"] == "/"
    assert client.get("/").status_code == 200


def test_web_login_mit_falschem_passwort_meldet_nicht_an(client, zugangsdaten):
    benutzername, _ = zugangsdaten["student"]
    client.post("/login", data={"username": benutzername, "password": "falsch"})

    antwort = client.get("/")

    assert antwort.status_code == 302
    assert antwort.headers["Location"] == "/login"


def test_api_login_liefert_benutzer_und_rolle(client, zugangsdaten):
    benutzername, passwort = zugangsdaten["pruefungsamt"]

    antwort = client.post("/auth/login", json={"username": benutzername, "password": passwort})

    assert antwort.status_code == 200
    assert antwort.get_json()["username"] == benutzername
    assert antwort.get_json()["role"] == "registrar"


def test_api_login_mit_falschem_passwort_wird_abgelehnt(client, zugangsdaten):
    benutzername, _ = zugangsdaten["student"]

    antwort = client.post("/auth/login", json={"username": benutzername, "password": "falsch"})

    assert antwort.status_code == 401


def test_api_login_mit_unbekanntem_benutzer_wird_abgelehnt(client):
    antwort = client.post("/auth/login", json={"username": "gibtesnicht", "password": "egal"})

    assert antwort.status_code == 401


def test_geschuetzter_endpunkt_ohne_anmeldung_ist_gesperrt(client):
    assert client.get("/grades").status_code == 401


def test_nach_logout_ist_geschuetzter_endpunkt_wieder_gesperrt(student):
    assert student.get("/grades").status_code == 200

    student.post("/auth/logout")

    assert student.get("/grades").status_code == 401
