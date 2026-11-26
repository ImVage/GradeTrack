KPI_LEISTE = b'class="kpi-strip"'


def test_dashboard_ohne_anmeldung_leitet_zum_login(client):
    antwort = client.get("/")

    assert antwort.status_code == 302
    assert antwort.headers["Location"] == "/login"


def test_dashboard_zeigt_studierenden_die_kpi_leiste(student):
    antwort = student.get("/")

    assert antwort.status_code == 200
    assert KPI_LEISTE in antwort.data


def test_dashboard_blendet_kpi_leiste_fuer_pruefungsamt_aus(pruefungsamt):
    antwort = pruefungsamt.get("/")

    assert antwort.status_code == 200
    assert KPI_LEISTE not in antwort.data


def test_health_check_antwortet(client):
    antwort = client.get("/health")

    assert antwort.status_code == 200
    assert antwort.get_json()["status"] == "ok"
