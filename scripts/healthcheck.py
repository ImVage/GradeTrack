import argparse
import http.client
import json
import sys
import time
from urllib.parse import SplitResult, urlsplit

STANDARD_URL = "http://127.0.0.1:8000/health"
MAX_ANTWORT_BYTES = 4096


def health_url(wert: str) -> SplitResult:
    teile = urlsplit(wert)
    if teile.scheme not in ("http", "https") or not teile.hostname:
        raise argparse.ArgumentTypeError(f"erwartet http(s)://host:port/health, nicht {wert!r}")
    return teile


def positive_zahl(wert: str) -> float:
    try:
        zahl = float(wert)
    except ValueError:
        raise argparse.ArgumentTypeError(f"keine Zahl: {wert!r}") from None
    if zahl <= 0:
        raise argparse.ArgumentTypeError(f"muss größer als 0 sein, nicht {wert!r}")
    return zahl


def frage_ab(url: SplitResult, timeout: float) -> tuple[int, bytes, float]:
    klasse = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    verbindung = klasse(url.hostname or "", url.port, timeout=timeout)
    start = time.monotonic()
    try:
        verbindung.request("GET", url.path or "/health", headers={"Accept": "application/json"})
        antwort = verbindung.getresponse()
        return antwort.status, antwort.read(MAX_ANTWORT_BYTES), time.monotonic() - start
    finally:
        verbindung.close()


def bewerte(url: SplitResult, timeout: float, max_dauer: float) -> tuple[bool, str]:
    try:
        status, inhalt, dauer = frage_ab(url, timeout)
    except ConnectionRefusedError:
        return False, "App nicht erreichbar (Verbindung abgelehnt)"
    except TimeoutError:
        return False, f"keine Antwort innerhalb von {timeout:g} s"
    except OSError as fehler:
        return False, f"App nicht erreichbar ({type(fehler).__name__})"
    except http.client.HTTPException:
        return False, "keine gültige HTTP-Antwort"

    try:
        daten = json.loads(inhalt)
    except ValueError:
        return False, f"HTTP {status}, Antwort ist kein JSON"
    if not isinstance(daten, dict):
        return False, f"HTTP {status}, unerwartetes Antwortformat"

    checks = daten.get("checks")
    checks = checks if isinstance(checks, dict) else {}
    fehlerhaft = sorted(name for name, ergebnis in checks.items() if ergebnis != "ok")

    if status != 200 or daten.get("status") != "ok":
        return False, f"HTTP {status}, fehlerhafte Prüfung: {', '.join(fehlerhaft) or 'unbekannt'}"
    if dauer > max_dauer:
        return False, f"Antwort zu langsam ({dauer:.2f} s, Grenze {max_dauer:g} s)"
    return True, f"HTTP 200 in {dauer:.2f} s, Prüfungen ok: {', '.join(sorted(checks)) or 'keine'}"


def main(argumente: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prüft, ob GradeTrack gesund ist. Exit-Code 0 = HEALTHY, 1 = UNHEALTHY, 2 = falscher Aufruf."
    )
    parser.add_argument("--url", type=health_url, default=health_url(STANDARD_URL), help=f"Standard: {STANDARD_URL}")
    parser.add_argument("--timeout", type=positive_zahl, default=5.0, help="Sekunden bis Abbruch, Standard: 5")
    parser.add_argument(
        "--max-dauer", type=positive_zahl, default=2.0, help="langsamere Antworten gelten als UNHEALTHY, Standard: 2"
    )
    optionen = parser.parse_args(argumente)

    gesund, meldung = bewerte(optionen.url, optionen.timeout, optionen.max_dauer)
    print(f"{'HEALTHY' if gesund else 'UNHEALTHY'}: {optionen.url.geturl()} - {meldung}")
    return 0 if gesund else 1


if __name__ == "__main__":
    sys.exit(main())
