import pytest


@pytest.fixture(scope="session")
def gradetrack_modul(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GRADETRACK_DB", str(tmp_path_factory.mktemp("import") / "grades.db"))
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
