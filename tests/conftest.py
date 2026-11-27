import pytest


@pytest.fixture(scope="session")
def gradetrack_modul(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GRADETRACK_DB", str(tmp_path_factory.mktemp("import") / "grades.db"))
        # Nur für Tests: fester Schlüssel, Beispielbenutzer, Cookies auch ohne HTTPS.
        mp.setenv("GRADETRACK_SECRET_KEY", "nur-fuer-tests-" + "x" * 32)
        mp.setenv("GRADETRACK_DEMO_DATA", "1")
        mp.setenv("GRADETRACK_SECURE_COOKIES", "0")
        import gradetrack

        yield gradetrack


@pytest.fixture
def app(gradetrack_modul, tmp_path):
    app = gradetrack_modul.app
    app.config.update(TESTING=True, DATABASE=str(tmp_path / "grades.db"))
    with app.app_context():
        gradetrack_modul.init_db()
    return app


@pytest.fixture
def client(app):
    return app.test_client()


ZUGANGSDATEN = {
    "student": ("tobias", "tobias123"),
    "pruefungsamt": ("pamt", "admin123"),
}


@pytest.fixture
def zugangsdaten():
    return ZUGANGSDATEN


def angemeldeter_client(app, rolle):
    client = app.test_client()
    benutzername, passwort = ZUGANGSDATEN[rolle]
    antwort = client.post("/auth/login", json={"username": benutzername, "password": passwort})
    assert antwort.status_code == 200
    return client


@pytest.fixture
def student(app):
    return angemeldeter_client(app, "student")


@pytest.fixture
def pruefungsamt(app):
    return angemeldeter_client(app, "pruefungsamt")
