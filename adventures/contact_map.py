from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

from core.location_privacy import can_view_location
from core.models import JournalContact

from .adif_parser import maidenhead_to_latlon


MISSING_ORIGIN_MESSAGE = (
    "A Location pin is required before contact paths can be mapped."
)
JOURNAL_CONTACTS_WITHOUT_ORIGIN_MESSAGE = (
    "This Journal's Location does not have coordinates. Contact markers are "
    "shown, but contact paths cannot be drawn."
)
NO_MAPPABLE_CONTACTS_MESSAGE = (
    "None of this Journal's contacts contain coordinates or grid squares that "
    "can be placed on the map."
)
NO_CONTACTS_MESSAGE = "This Journal has no contacts to map."
PRIVATE_ORIGIN_MESSAGE = (
    "Contact paths are hidden because this Adventure uses a Private Location."
)
PRIVATE_JOURNAL_ORIGIN_MESSAGE = (
    "Contact paths are hidden because this Journal uses a Private Location."
)
LINE_LIMIT = 250


def coordinate_pair(latitude, longitude):
    try:
        latitude = float(Decimal(str(latitude)))
        longitude = float(Decimal(str(longitude)))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    if latitude == 0 and longitude == 0:
        return None
    return latitude, longitude


def contact_coordinates(contact: JournalContact, user):
    direct = coordinate_pair(contact.latitude, contact.longitude)
    if direct is not None:
        return direct, "Exact coordinates", False
    grid = maidenhead_to_latlon(contact.grid_square)
    if grid is not None:
        return grid, "Grid-square center", True
    resolved = contact.resolved_location
    if resolved is not None and can_view_location(user, resolved):
        coordinates = coordinate_pair(resolved.latitude, resolved.longitude)
        if coordinates is not None:
            return coordinates, "Approximate resolved park location", True
    return None, "Unavailable", False


def build_contact_map(
    adventure,
    contacts: Iterable[JournalContact],
    user,
    *,
    journal_entry=None,
):
    contacts = list(contacts)
    location = journal_entry.location if journal_entry is not None else adventure.location
    if location is not None and not can_view_location(user, location):
        return {
            "available": False,
            "message": (
                PRIVATE_JOURNAL_ORIGIN_MESSAGE
                if journal_entry is not None
                else PRIVATE_ORIGIN_MESSAGE
            ),
            "total": len(contacts),
            "mapped": 0,
            "unmapped": len(contacts),
            "contacts": [],
            "origin": None,
            "has_map_points": False,
            "path_count": 0,
            "filters": {},
        }

    if journal_entry is not None:
        origin = coordinate_pair(journal_entry.latitude, journal_entry.longitude)
    else:
        origin = None if location is None else coordinate_pair(
            location.latitude, location.longitude
        )
    if origin is None and journal_entry is None:
        return {
            "available": False,
            "message": MISSING_ORIGIN_MESSAGE,
            "total": len(contacts),
            "mapped": 0,
            "unmapped": len(contacts),
            "contacts": [],
            "origin": None,
            "has_map_points": False,
            "path_count": 0,
            "filters": {},
        }

    points = []
    unmapped_contacts = []
    journals = {}
    bands = set()
    modes = set()
    for contact in contacts:
        journal_title = contact.journal_entry.title or "Journal Entry" if contact.journal_entry_id else "Adventure Contact"
        coordinates, source, approximate = contact_coordinates(contact, user)
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

    origin_data = None
    if origin is not None:
        origin_data = {
            "latitude": origin[0],
            "longitude": origin[1],
            "name": (
                location.name
                if location is not None
                else journal_entry.title or "Journal Location"
            ),
            "label": (
                "Journal Location"
                if journal_entry is not None
                else "Adventure Location"
            ),
        }

    message = ""
    if journal_entry is not None:
        if not contacts:
            message = NO_CONTACTS_MESSAGE
        elif not points:
            message = NO_MAPPABLE_CONTACTS_MESSAGE
        elif origin is None:
            message = JOURNAL_CONTACTS_WITHOUT_ORIGIN_MESSAGE

    return {
        "available": True,
        "message": message,
        "total": len(contacts),
        "mapped": len(points),
        "unmapped": len(unmapped_contacts),
        "origin": origin_data,
        "has_map_points": bool(origin_data or points),
        "path_count": len(points) if origin_data else 0,
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
        "line_limit": None if journal_entry is not None else LINE_LIMIT,
        "lines_default": bool(origin_data) and (
            journal_entry is not None or len(points) <= LINE_LIMIT
        ),
    }
