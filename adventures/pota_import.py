from dataclasses import dataclass, field
from datetime import datetime
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

def parse_pota_history(text, max_rows=1000):
    rows, ignored, invalid = [], 0, []
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        normalized = raw.replace("\u00a0", " ").strip()
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
