from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

from core.location_privacy import can_view_location
from core.models import JournalContact

from .adif_parser import maidenhead_to_latlon


MISSING_ORIGIN_MESSAGE = (
    "A Location pin is required before contact paths can be mapped."
)
PRIVATE_ORIGIN_MESSAGE = (
    "Contact paths are hidden because this Adventure uses a Private Location."
)
LINE_LIMIT = 250


def _coordinate_pair(latitude, longitude):
    try:
        latitude = float(Decimal(str(latitude)))
        longitude = float(Decimal(str(longitude)))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return latitude, longitude


def _contact_coordinates(contact: JournalContact):
    direct = _coordinate_pair(contact.latitude, contact.longitude)
    if direct is not None:
        return direct, "Exact coordinates", False
    grid = maidenhead_to_latlon(contact.grid_square)
    if grid is not None:
        return grid, "Grid-square center", True
    return None, "Unavailable", False


def build_contact_map(adventure, contacts: Iterable[JournalContact], user):
    contacts = list(contacts)
    location = adventure.location
    if location is not None and not can_view_location(user, location):
        return {
            "available": False,
            "message": PRIVATE_ORIGIN_MESSAGE,
            "total": len(contacts),
            "mapped": 0,
            "unmapped": len(contacts),
            "contacts": [],
            "origin": None,
            "filters": {},
        }

    origin = None if location is None else _coordinate_pair(
        location.latitude, location.longitude
    )
    if origin is None:
        return {
            "available": False,
            "message": MISSING_ORIGIN_MESSAGE,
            "total": len(contacts),
            "mapped": 0,
            "unmapped": len(contacts),
            "contacts": [],
            "origin": None,
            "filters": {},
        }

    points = []
    unmapped_contacts = []
    journals = {}
    bands = set()
    modes = set()
    for contact in contacts:
        journal_title = contact.journal_entry.title or "Journal Entry" if contact.journal_entry_id else "Adventure Contact"
        coordinates, source, approximate = _contact_coordinates(contact)
        contact.map_coordinate_source = source
        contact.is_mappable = coordinates is not None
        if coordinates is None:
            unmapped_contacts.append(
                {
                    "callsign": contact.callsign,
                    "journal": journal_title,
                    "date": contact.qso_date.isoformat(),
                }
            )
            continue
        if contact.journal_entry_id:
            journals[contact.journal_entry_id] = journal_title
        if contact.band:
            bands.add(contact.band)
        if contact.mode:
            modes.add(contact.mode)
        points.append(
            {
                "id": contact.pk,
                "latitude": coordinates[0],
                "longitude": coordinates[1],
                "coordinate_source": source,
                "approximate": approximate,
                "callsign": contact.callsign,
                "date": contact.qso_date.isoformat(),
                "time": contact.time_on.strftime("%H:%M") if contact.time_on else "",
                "band": contact.band,
                "frequency": str(contact.frequency) if contact.frequency is not None else "",
                "mode": contact.mode,
                "grid_square": contact.grid_square,
                "country": contact.country,
                "state": contact.state,
                "journal_id": contact.journal_entry_id,
                "journal": journal_title,
            }
        )

    return {
        "available": True,
        "message": "",
        "total": len(contacts),
        "mapped": len(points),
        "unmapped": len(unmapped_contacts),
        "origin": {
            "latitude": origin[0],
            "longitude": origin[1],
            "name": location.name,
        },
        "contacts": points,
        "unmapped_contacts": unmapped_contacts,
        "filters": {
            "journals": [
                {"id": key, "name": value}
                for key, value in sorted(journals.items(), key=lambda item: item[1].lower())
            ],
            "bands": sorted(bands, key=str.lower),
            "modes": sorted(modes, key=str.lower),
        },
        "line_limit": LINE_LIMIT,
        "lines_default": len(points) <= LINE_LIMIT,
    }
