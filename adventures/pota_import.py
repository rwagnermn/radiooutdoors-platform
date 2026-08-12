from dataclasses import dataclass, field
from datetime import datetime, timedelta
import csv
import io
import re

DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y")
PARK_RE = re.compile(r"^[A-Z0-9]{1,5}-\d{3,6}$", re.I)
CALL_RE = re.compile(r"^[A-Z0-9]{1,3}\d[A-Z0-9/]{1,12}$", re.I)
ROW_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/(?:\d{2}|\d{4}))\s+"
    r"(?P<callsign>[A-Z0-9/]+)\s+"
    r"(?P<reference>[A-Z0-9]{1,5}-\d{3,6})\s+"
    r"(?P<park>.+?)\s+"
    r"(?P<entity>[A-Z]{2}-[A-Z0-9-]+)\s+"
    r"(?P<cw>\d+)\s+(?P<data>\d+)\s+(?P<phone>\d+)\s+(?P<total>\d+)$",
    re.I,
)

def clean_pota_park_name(reference, value):
    name = re.sub(r"\s+", " ", (value or "").replace("\u00a0", " ")).strip()
    reference = (reference or "").strip()
    if reference:
        name = re.sub(rf"^{re.escape(reference)}\s*", "", name, flags=re.IGNORECASE)
    return re.sub(r"^[\s\-\u2013\u2014:]+", "", name).strip()

@dataclass
class PotaRow:
    line_number: int
    activation_date: str = ""
    callsign: str = ""
    park_reference: str = ""
    park_name: str = ""
    entity: str = ""
    cw: int = 0
    data: int = 0
    phone: int = 0
    total: int = 0
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def as_dict(self):
        return self.__dict__.copy()

def _date(value):
    for fmt in DATE_FORMATS:
        try: return datetime.strptime(value.strip(), fmt).date()
        except ValueError: pass
    return None

def normalize_pota_page_paste(text):
    """Normalize copied POTA page lines while retaining original line numbers."""
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        normalized = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", raw.replace("\u00a0", " "))
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if normalized:
            yield number, normalized

def parse_pota_history(text, max_rows=1000):
    rows, ignored, invalid = [], 0, []
    for number, normalized in normalize_pota_page_paste(text):
        match = ROW_RE.match(normalized)
        if not match:
            if re.match(r"^\d{4}-\d{2}-\d{2}\b|^\d{1,2}/\d{1,2}/\d{2,4}\b", normalized):
                invalid.append({"line_number": number, "reason": "The activation row does not contain a valid date, callsign, POTA reference, park name, entity, and four contact totals."})
            else:
                ignored += 1
            continue
        if len(rows) + len(invalid) >= max_rows:
            raise ValueError(f"No more than {max_rows} activation rows may be imported at once.")
        values = match.groupdict()
        parsed_date = _date(values["date"])
        if parsed_date is None:
            invalid.append({"line_number": number, "reason": "The activation date is not valid."})
            continue
        if not CALL_RE.match(values["callsign"]):
            invalid.append({"line_number": number, "reason": "The activation callsign is not valid."})
            continue
        row = PotaRow(number)
        row.activation_date = parsed_date.isoformat()
        row.callsign = values["callsign"].upper()
        row.park_reference = values["reference"].upper()
        row.park_name = clean_pota_park_name(row.park_reference, values["park"])
        row.entity = values["entity"].upper()
        row.cw = int(values["cw"])
        row.data = int(values["data"])
        row.phone = int(values["phone"])
        row.total = int(values["total"])
        if row.cw + row.data + row.phone != row.total:
            row.warnings.append("The mode counts do not equal the supplied total.")
        rows.append(row)
    return rows, ignored, invalid


HUNTER_HEADER_ALIASES = {
    "date": {"date", "qso date", "qso_date", "activation date"},
    "time": {"time", "qso time", "qso_time", "time on", "time_on"},
    "station_callsign": {"station callsign", "station", "hunter callsign", "my callsign"},
    "operator_callsign": {"operator callsign", "operator"},
    "worked_callsign": {"worked callsign", "callsign", "activator callsign"},
    "band": {"band"},
    "mode": {"mode"},
    "park_reference": {"park reference", "reference", "park", "pota reference"},
    "park_name": {"park name", "name"},
    "entity": {"state/entity", "state", "entity", "location"},
    "source_id": {"id", "qso id", "qso_id", "contact id"},
    "is_p2p": {"p2p", "park to park", "park-to-park"},
}


def _normalized_header(value):
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _hunter_header_map(headers):
    result = {}
    normalized = [_normalized_header(value) for value in headers]
    for key, aliases in HUNTER_HEADER_ALIASES.items():
        for index, value in enumerate(normalized):
            if value in aliases:
                result[key] = index
                break
    return result


def _hunter_time(value):
    cleaned = re.sub(r"[^0-9:]", "", (value or "").strip())
    for fmt in ("%H:%M:%S", "%H:%M", "%H%M%S", "%H%M"):
        try:
            return datetime.strptime(cleaned, fmt).time()
        except ValueError:
            pass
    return None


def _hunter_qso(values, mapping, line_number, *, is_p2p=False):
    get = lambda key: values[mapping[key]].strip() if key in mapping and mapping[key] < len(values) else ""
    parsed_date = _date(get("date"))
    parsed_time = _hunter_time(get("time"))
    callsign = (get("station_callsign") or get("operator_callsign")).upper()
    reference = get("park_reference").upper()
    if not parsed_date or not parsed_time or not CALL_RE.match(callsign) or not PARK_RE.match(reference):
        return None
    return {
        "line_number": line_number, "qso_at": datetime.combine(parsed_date, parsed_time),
        "activation_date": parsed_date.isoformat(), "callsign": callsign,
        "station_callsign": get("station_callsign").upper(),
        "operator_callsign": get("operator_callsign").upper(),
        "worked_callsign": get("worked_callsign").upper(),
        "park_reference": reference,
        "park_name": clean_pota_park_name(reference, get("park_name")) or reference,
        "entity": get("entity").upper(), "band": get("band").upper(),
        "mode": get("mode").upper(), "source_id": get("source_id"),
        "is_p2p": is_p2p or get("is_p2p").strip().casefold() in {"p2p", "yes", "true", "1"},
    }


DIRECT_HUNTER_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<time>\d{2}:\d{2}(?::\d{2})?)\s+"
    r"(?P<station>[A-Z0-9/]+)\s+(?P<operator>[A-Z0-9/]+)\s+(?P<worked>[A-Z0-9/]+)\s+"
    r"(?P<band>\d+(?:\.\d+)?(?:CM|MM|M))\s+"
    r"(?P<mode>[A-Z]+(?:\s*\([^)]+\))?)\s+"
    r"(?P<entity>[A-Z]{2}-[A-Z0-9-]+)\s+"
    r"(?P<reference>[A-Z0-9]{1,5}-\d{3,6})\s+(?P<park>.+)$",
    re.I,
)


def _hunter_block_failure(logical):
    checks = (
        (r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}", "date/time"),
        (r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?\s+[A-Z0-9/]+\s+[A-Z0-9/]+\s+[A-Z0-9/]+", "station, operator, and worked callsigns"),
        (r"\b\d+(?:\.\d+)?(?:CM|MM|M)\b", "band"),
        (r"\b(?:DATA|PHONE|CW|SSB|FM|AM)(?:\s*\([^)]+\))?\b", "mode"),
        (r"\b[A-Z]{2}-[A-Z0-9-]+\b", "location/entity"),
        (r"\b[A-Z0-9]{1,5}-\d{3,6}\b", "POTA park reference"),
    )
    for pattern, label in checks:
        if not re.search(pattern, logical, re.I):
            return f"Missing or invalid {label}."
    return "The park name or logical field order could not be determined."


def _screen_copy_hunter_rows(text, max_rows):
    # Use the same normalized page lines as Activation History, then interpret
    # Hunter-specific logical record boundaries and fields.
    page_lines = list(normalize_pota_page_paste(text))
    cells = []
    for line_number, line in page_lines:
        parts = [part.strip() for part in line.split("|") if part.strip()] if "|" in line else [line]
        for part in parts:
            boundary = re.match(
                r"^Hunter(?P<row_p2p>P2P)?(?:\s+(?:(?P<badge_p2p>P2P)\s+)?"
                r"(?P<remainder>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?))?$",
                part,
                re.I,
            )
            if boundary:
                cells.append((line_number, "Hunter"))
                if boundary.group("row_p2p") or boundary.group("badge_p2p"):
                    cells.append((line_number, "P2P"))
                if boundary.group("remainder"):
                    cells.append((line_number, boundary.group("remainder")))
            else:
                cells.append((line_number, part))
    boundaries = [index for index, (_, value) in enumerate(cells) if value.casefold() == "hunter"]
    if not boundaries:
        return None
    rows, invalid = [], []
    ignored = boundaries[0]
    for index, boundary in enumerate(boundaries):
        if len(rows) + len(invalid) >= max_rows:
            raise ValueError(f"No more than {max_rows} Hunter Log QSOs may be imported at once.")
        end = boundaries[index + 1] if index + 1 < len(boundaries) else len(cells)
        values = [value for _, value in cells[boundary + 1:end]]
        is_p2p = bool(values and values[0].casefold() == "p2p")
        if is_p2p:
            values = values[1:]
        logical = " ".join(values)
        match = DIRECT_HUNTER_RE.match(logical)
        line_number = cells[boundary][0]
        # A whole-page browser copy normally has one visual cell per line.
        # Consume the fixed logical fields so footer text after the last row is
        # ignored instead of being appended to the final park name.
        if len(values) >= 4 and re.match(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}", values[0]) and CALL_RE.match(values[1]) and CALL_RE.match(values[2]) and re.match(r"^[A-Z0-9/]+\s+\d+(?:\.\d+)?(?:CM|MM|M)\b", values[3], re.I):
            # Actual POTA whole-page copies use four physical lines: date/time,
            # station, operator, then all remaining QSO fields. Stop there so
            # navigation/footer lines after the final record remain page junk.
            compact = " ".join(values[:4])
            match = DIRECT_HUNTER_RE.match(compact)
            ignored += max(0, len(values) - 4)
        elif len(values) >= 8 and re.match(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}", values[0]):
            reference_match = re.match(r"^(?P<reference>[A-Z0-9]{1,5}-\d{3,6})(?:\s+(?P<name>.+))?$", values[7], re.I)
            park_name = values[8] if len(values) > 8 else (reference_match.group("name") if reference_match else "")
            compact = " ".join(values[:7] + [reference_match.group("reference") if reference_match else values[7], park_name])
            match = DIRECT_HUNTER_RE.match(compact)
            ignored += max(0, len(values) - 9)
        if not match:
            excerpt = re.sub(r"\s+", " ", logical)[:180]
            invalid.append({"line_number": line_number, "reason": _hunter_block_failure(logical), "excerpt": excerpt})
            continue
        values = match.groupdict()
        row = _hunter_qso(
            [values["date"], values["time"], values["station"], values["operator"], values["worked"], values["band"], values["mode"], values["reference"], values["park"], values["entity"], ""],
            {"date": 0, "time": 1, "station_callsign": 2, "operator_callsign": 3, "worked_callsign": 4, "band": 5, "mode": 6, "park_reference": 7, "park_name": 8, "entity": 9, "source_id": 10},
            line_number,
            is_p2p=is_p2p,
        )
        if row:
            rows.append(row)
        else:
            invalid.append({"line_number": line_number, "reason": "A reconstructed Hunter record contained an invalid callsign, date/time, or park reference.", "excerpt": logical[:180]})
    return rows, ignored, invalid


def parse_pota_hunter_log(text, max_rows=5000):
    """Parse a copied/downloaded POTA Hunter Log table into normalized QSO rows."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return [], 0, []
    screen_copy = _screen_copy_hunter_rows(text, max_rows)
    if screen_copy is not None:
        return screen_copy
    header_line = next((line for line in lines if ("\t" in line or "," in line) and "date" in line.lower() and ("park" in line.lower() or "reference" in line.lower())), lines[0])
    delimiter = "\t" if "\t" in header_line else ","
    records = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter))
    header_index = next((i for i, values in enumerate(records) if "date" in " ".join(values).lower() and any("park" in value.lower() or "reference" in value.lower() for value in values)), None)
    if header_index is None:
        return [], len(records), []
    mapping = _hunter_header_map(records[header_index])
    required = {"date", "time", "park_reference"}
    if not required.issubset(mapping) or not ({"station_callsign", "operator_callsign"} & set(mapping)):
        return [], header_index + 1, [{"line_number": header_index + 1, "reason": "The Hunter Log header must include date, time, station/operator callsign, and park reference columns."}]

    rows, invalid = [], []
    for line_number, values in enumerate(records[header_index + 1:], header_index + 2):
        if len(rows) + len(invalid) >= max_rows:
            raise ValueError(f"No more than {max_rows} Hunter Log QSOs may be imported at once.")
        row = _hunter_qso(values, mapping, line_number)
        if row is None:
            invalid.append({"line_number": line_number, "reason": "The QSO must contain a valid date, time, station/operator callsign, and POTA park reference."})
            continue
        rows.append(row)
    return rows, header_index + 1, invalid


def group_pota_hunter_qsos(rows, session_gap=timedelta(hours=4)):
    """Group Hunter QSOs into activation-like sessions separated by inactivity."""
    groups = []
    by_identity = {}
    for row in sorted(rows, key=lambda item: (item["callsign"], item["park_reference"], item["activation_date"], item["qso_at"])):
        key = (row["callsign"], row["park_reference"], row["activation_date"])
        sessions = by_identity.setdefault(key, [])
        if not sessions or row["qso_at"] - sessions[-1][-1]["qso_at"] > session_gap:
            sessions.append([])
        sessions[-1].append(row)
    for sessions in by_identity.values():
        for session_number, session in enumerate(sessions, 1):
            first, last = session[0], session[-1]
            modes = sorted({row["mode"] for row in session if row["mode"]})
            bands = sorted({row["band"] for row in session if row["band"]})
            groups.append({
                "activation_date": first["activation_date"], "callsign": first["callsign"],
                "station_callsign": first["station_callsign"], "operator_callsign": first["operator_callsign"],
                "park_reference": first["park_reference"], "park_name": first["park_name"], "entity": first["entity"],
                "cw": sum(row["mode"] == "CW" for row in session),
                "data": sum(row["mode"].startswith("DATA") or row["mode"] in {"DIGITAL", "FT8", "FT4", "RTTY", "PSK31"} for row in session),
                "phone": sum(row["mode"].startswith("PHONE") or row["mode"] in {"SSB", "FM", "AM"} for row in session),
                "total": len(session), "qso_count": len(session), "bands": bands, "modes": modes,
                "first_qso_time": first["qso_at"].time().isoformat(timespec="minutes"),
                "last_qso_time": last["qso_at"].time().isoformat(timespec="minutes"),
                "session_number": session_number,
                "source_row_ids": [row["source_id"] for row in session if row["source_id"]],
                "source_line_numbers": [row["line_number"] for row in session],
                "worked_callsigns": sorted({row["worked_callsign"] for row in session if row["worked_callsign"]}),
                "errors": [], "warnings": [],
            })
    return sorted(groups, key=lambda row: (row["activation_date"], row["first_qso_time"], row["park_reference"]))
