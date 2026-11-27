import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

SKRIPT = Path(__file__).resolve().parent.parent / "scripts" / "healthcheck.py"


def fuehre_aus(*argumente):
    return subprocess.run(
        [sys.executable, str(SKRIPT), *argumente], capture_output=True, text=True, timeout=30, check=False
    )


@pytest.fixture
def health_url(app):
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/health"
    server.shutdown()
    thread.join()


@pytest.fixture
def freier_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_skript_meldet_healthy(health_url):
    ergebnis = fuehre_aus("--url", health_url)

    assert ergebnis.returncode == 0
    assert ergebnis.stdout.startswith("HEALTHY:")


def test_skript_meldet_unhealthy_ohne_datenbank(app, health_url):
    os.remove(app.config["DATABASE"])

    ergebnis = fuehre_aus("--url", health_url)

    assert ergebnis.returncode == 1
    assert ergebnis.stdout.startswith("UNHEALTHY:")
    assert "HTTP 503" in ergebnis.stdout
    assert "database" in ergebnis.stdout


def test_skript_meldet_unhealthy_wenn_app_nicht_laeuft(freier_port):
    ergebnis = fuehre_aus("--url", f"http://127.0.0.1:{freier_port}/health")

    assert ergebnis.returncode == 1
    assert ergebnis.stdout.startswith("UNHEALTHY:")
    assert "nicht erreichbar" in ergebnis.stdout


def test_skript_meldet_unhealthy_bei_langsamer_antwort(health_url):
    ergebnis = fuehre_aus("--url", health_url, "--max-dauer", "0.000001")

    assert ergebnis.returncode == 1
    assert "zu langsam" in ergebnis.stdout


@pytest.mark.parametrize("url", ["ftp://127.0.0.1/health", "kein-url"])
def test_skript_lehnt_ungueltige_url_ab(url):
    ergebnis = fuehre_aus("--url", url)

    assert ergebnis.returncode == 2
