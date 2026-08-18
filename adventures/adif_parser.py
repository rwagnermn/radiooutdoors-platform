from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from math import asin, cos, radians, sin, sqrt
import re


KM_TO_MILES = 0.621371


@dataclass(frozen=True)
class ParsedContact:
    qso_date: date
    time_on: time | None
    callsign: str
    band: str
    frequency: float | None
    mode: str
    name: str
    state: str
    country: str
    distance_miles: int | None
    comment: str
    grid_square: str
    latitude: float | None
    longitude: float | None

    def as_dict(self) -> dict:
        return {
            "qso_date": self.qso_date.isoformat(),
            "time_on": self.time_on.isoformat() if self.time_on else "",
            "callsign": self.callsign,
            "band": self.band,
            "frequency": self.frequency,
            "mode": self.mode,
            "name": self.name,
            "state": self.state,
            "country": self.country,
            "distance_miles": self.distance_miles,
            "comment": self.comment,
            "grid_square": self.grid_square,
            "latitude": self.latitude,
            "longitude": self.longitude,
        }


def parse_adif_bytes(
    data: bytes,
    *,
    origin_latitude: float | None = None,
    origin_longitude: float | None = None,
) -> list[ParsedContact]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1", errors="replace")

    return parse_adif_text(
        text,
        origin_latitude=origin_latitude,
        origin_longitude=origin_longitude,
    )


def parse_adif_bytes_with_counts(
    data: bytes,
    *,
    origin_latitude: float | None = None,
    origin_longitude: float | None = None,
) -> tuple[list[ParsedContact], int]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1", errors="replace")

    records = _read_records(text)
    contacts = parse_adif_text(
        text,
        origin_latitude=origin_latitude,
        origin_longitude=origin_longitude,
    )
    return contacts, len(records) - len(contacts)


def parse_adif_text(
    text: str,
    *,
    origin_latitude: float | None = None,
    origin_longitude: float | None = None,
) -> list[ParsedContact]:
    contacts = []

    for record in _read_records(text):
        callsign = record.get("CALL", "").strip().upper()
        qso_date = _parse_date(record.get("QSO_DATE", ""))

        if not callsign or qso_date is None:
            continue

        grid_square = record.get("GRIDSQUARE", "").strip().upper()
        my_grid_square = record.get("MY_GRIDSQUARE", "").strip().upper()
        mode = (
            record.get("SUBMODE", "").strip().upper()
            or record.get("MODE", "").strip().upper()
        )
        latitude = _parse_coordinate(record.get("LAT", ""), "latitude")
        longitude = _parse_coordinate(record.get("LON", ""), "longitude")
        if latitude is None or longitude is None:
            latitude = longitude = None

        contacts.append(
            ParsedContact(
                qso_date=qso_date,
                time_on=_parse_time(record.get("TIME_ON", "")),
                callsign=callsign,
                band=record.get("BAND", "").strip().upper(),
                frequency=_parse_float(record.get("FREQ", "")),
                mode=mode,
                name=record.get("NAME", "").strip(),
                state=record.get("STATE", "").strip(),
                country=record.get("COUNTRY", "").strip(),
                distance_miles=_distance_miles(
                    record,
                    origin_latitude,
                    origin_longitude,
                    grid_square,
                    my_grid_square,
                ),
                comment=(
                    record.get("COMMENT", "").strip()
                    or record.get("NOTES", "").strip()
                ),
                grid_square=grid_square,
                latitude=latitude,
                longitude=longitude,
            )
        )

    contacts.sort(
        key=lambda item: (
            item.qso_date,
            item.time_on or time.min,
            item.callsign,
        )
    )
    return contacts


def _read_records(text: str) -> list[dict[str, str]]:
    records = []
    record = {}
    index = 0

    while index < len(text):
        start = text.find("<", index)
        if start == -1:
            break

        end = text.find(">", start + 1)
        if end == -1:
            break

        tag = text[start + 1:end].strip()
        upper_tag = tag.upper()

        if upper_tag == "EOR":
            if record:
                records.append(record)
                record = {}
            index = end + 1
            continue

        if upper_tag == "EOH":
            record = {}
            index = end + 1
            continue

        parts = tag.split(":")
        if len(parts) < 2:
            index = end + 1
            continue

        try:
            field_length = int(parts[1])
        except ValueError:
            index = end + 1
            continue

        value_start = end + 1
        value_end = value_start + field_length
        record[parts[0].strip().upper()] = text[value_start:value_end]
        index = value_end

    if record:
        records.append(record)

    return records


def _parse_date(value: str) -> date | None:
    value = value.strip()

    if len(value) < 8 or not value[:8].isdigit():
        return None

    try:
        return date(
            int(value[0:4]),
            int(value[4:6]),
            int(value[6:8]),
        )
    except ValueError:
        return None


def _parse_time(value: str) -> time | None:
    digits = "".join(character for character in value if character.isdigit())

    if len(digits) < 4:
        return None

    try:
        return time(
            int(digits[0:2]),
            int(digits[2:4]),
            int(digits[4:6]) if len(digits) >= 6 else 0,
        )
    except ValueError:
        return None


def _parse_float(value: str) -> float | None:
    try:
        return float(value.strip()) if value.strip() else None
    except ValueError:
        return None


def _parse_coordinate(value: str, axis: str) -> float | None:
    value = value.strip().upper()
    if not value:
        return None
    try:
        result = float(value)
    except ValueError:
        match = re.fullmatch(r"([NSEW])\s*(\d{1,3})[\s:]+(\d+(?:\.\d+)?)", value)
        if not match:
            return None
        direction, degrees, minutes = match.groups()
        result = float(degrees) + float(minutes) / 60
        if direction in {"S", "W"}:
            result = -result
        if axis == "latitude" and direction not in {"N", "S"}:
            return None
        if axis == "longitude" and direction not in {"E", "W"}:
            return None
    limit = 90 if axis == "latitude" else 180
    return result if -limit <= result <= limit else None

def _distance_miles(
    record: dict[str, str],
    origin_latitude: float | None,
    origin_longitude: float | None,
    grid_square: str,
    my_grid_square: str,
) -> int | None:
    stored_distance = record.get("DISTANCE", "").strip()

    if stored_distance:
        try:
            return round(float(stored_distance) * KM_TO_MILES)
        except ValueError:
            pass

    destination = maidenhead_to_latlon(grid_square)

    if destination is None:
        return None

    if origin_latitude is not None and origin_longitude is not None:
        origin = (origin_latitude, origin_longitude)
    else:
        origin = maidenhead_to_latlon(my_grid_square)

    if origin is None:
        return None

    return round(
        haversine_miles(
            origin[0],
            origin[1],
            destination[0],
            destination[1],
        )
    )


MAIDENHEAD_GRID_RE = re.compile(
    r"^[A-R]{2}\d{2}(?:[A-X]{2}(?:\d{2})?)?$",
    re.IGNORECASE,
)


def normalize_maidenhead_grid(grid: str) -> str:
    """Return a normalized 4-, 6-, or 8-character Maidenhead grid."""
    normalized = str(grid or "").strip().upper()
    return normalized if MAIDENHEAD_GRID_RE.fullmatch(normalized) else ""


def maidenhead_to_latlon(grid: str) -> tuple[float, float] | None:
    grid = normalize_maidenhead_grid(grid)
    if not grid:
        return None

    longitude = (ord(grid[0]) - ord("A")) * 20 - 180
    latitude = (ord(grid[1]) - ord("A")) * 10 - 90
    longitude += int(grid[2]) * 2
    latitude += int(grid[3])

    longitude_size = 2.0
    latitude_size = 1.0

    if len(grid) >= 6:
        longitude += (ord(grid[4]) - ord("A")) * (5 / 60)
        latitude += (ord(grid[5]) - ord("A")) * (2.5 / 60)
        longitude_size = 5 / 60
        latitude_size = 2.5 / 60

    if len(grid) == 8:
        longitude += int(grid[6]) * (0.5 / 60)
        latitude += int(grid[7]) * (0.25 / 60)
        longitude_size = 0.5 / 60
        latitude_size = 0.25 / 60

    return (
        latitude + latitude_size / 2,
        longitude + longitude_size / 2,
    )


def haversine_miles(
    latitude_1: float,
    longitude_1: float,
    latitude_2: float,
    longitude_2: float,
) -> float:
    radius = 3958.7613
    lat_1 = radians(latitude_1)
    lat_2 = radians(latitude_2)
    delta_lat = radians(latitude_2 - latitude_1)
    delta_lon = radians(longitude_2 - longitude_1)

    value = (
        sin(delta_lat / 2) ** 2
        + cos(lat_1) * cos(lat_2) * sin(delta_lon / 2) ** 2
    )

    return radius * 2 * asin(sqrt(value))
