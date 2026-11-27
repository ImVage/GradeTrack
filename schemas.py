"""Eingabemodelle für GradeTrack (Fail Fast).

Jede Eingabe wird am Eingang gegen ein Schema geprüft: Format, Datentyp, erlaubte Werte
und Wertebereich. Ungültiges wird sofort abgelehnt und nie "repariert".

- strict: keine stillen Umwandlungen, z. B. wird "5" nicht zu 5.
- extra="forbid": unbekannte Felder sind ein Fehler, statt ignoriert zu werden.
Formulare und URL-Parameter liefern immer Text. Sie werden deshalb mit strict=False
geprüft, sodass "5" dort als Zahl gelten darf. Alle anderen Regeln gelten genauso.
"""

import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

ModulCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2,5}-\d{4}$")]
Benutzername = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{3,32}$")]
Note = Annotated[float, Field(ge=1.0, le=5.0)]
Ects = Annotated[int, Field(ge=1, le=30)]
Semester = Annotated[int, Field(ge=1, le=8)]
Versuch = Annotated[int, Field(ge=1, le=3)]
Kommentar = Annotated[str, StringConstraints(max_length=500)]
Status = Literal["pending", "approved"]
Rolle = Literal["student", "registrar"]
Sortierung = Literal["id", "semester", "grade", "module_code", "exam_date", "status"]


class Eingabe(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", str_strip_whitespace=True)


def pruefe_datum(datum: datetime.date | None) -> datetime.date | None:
    if datum is not None and datum > datetime.date.today():
        raise ValueError("Prüfungsdatum darf nicht in der Zukunft liegen")
    return datum


class LoginEingabe(Eingabe):
    # Bewusst nur Längen, kein Format: Die Meldung soll nicht verraten, ob ein Name gültig wäre.
    username: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class NoteNeu(Eingabe):
    module_code: ModulCode
    grade: Note
    ects: Ects
    semester: Semester
    exam_date: datetime.date | None = None
    attempt: Versuch = 1
    comment: Kommentar = ""
    # Nur das Prüfungsamt darf eine Note für jemand anderen eintragen (Prüfung in der App).
    student_id: Annotated[int, Field(ge=1)] | None = None

    _datum = field_validator("exam_date")(pruefe_datum)


class NoteAenderung(Eingabe):
    # Status, Bestätigung und Zuordnung zu Studierenden sind hier absichtlich nicht dabei.
    module_code: ModulCode | None = None
    grade: Note | None = None
    ects: Ects | None = None
    semester: Semester | None = None
    exam_date: datetime.date | None = None
    attempt: Versuch | None = None
    comment: Kommentar | None = None

    _datum = field_validator("exam_date")(pruefe_datum)

    @model_validator(mode="after")
    def mindestens_ein_feld(self) -> "NoteAenderung":
        if not self.model_fields_set:
            raise ValueError("Keine Felder zum Aktualisieren")
        return self


class NotenFilter(Eingabe):
    semester: Semester | None = None
    student_id: Annotated[int, Field(ge=1)] | None = None
    status: Status | None = None
    sort: Sortierung = "id"


class StatistikFilter(Eingabe):
    semester: Semester | None = None
    student_id: Annotated[int, Field(ge=1)] | None = None


class ModulNeu(Eingabe):
    code: ModulCode
    title: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    ects: Ects
    semester: Semester


class ModulSuche(Eingabe):
    search: Annotated[str, StringConstraints(max_length=50)] | None = None


class BenutzerNeu(Eingabe):
    username: Benutzername
    full_name: Annotated[str, StringConstraints(min_length=1, max_length=100)] | None = None
    password: Annotated[str, StringConstraints(min_length=12, max_length=128)]
    role: Rolle = "student"


class DashboardFilter(Eingabe):
    semester: Semester | None = None
    status: Status | None = None
    student_id: Annotated[int, Field(ge=1)] | None = None
    search: Annotated[str, StringConstraints(max_length=50)] | None = None
    tab: Literal["overview", "add", "modules", "users"] = "overview"
