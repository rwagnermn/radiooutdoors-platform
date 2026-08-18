from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core import signing

from .adif_parser import maidenhead_to_latlon, normalize_maidenhead_grid


GEOGRAPHY_SIGNING_SALT = "radio-outdoors.contact-qrz-geography.v1"
SIX_PLACES = Decimal("0.000001")


@dataclass(frozen=True)
class ContactGeography:
    grid_square: str = ""
    latitude: Decimal | None = None
    longitude: Decimal | None = None

    @property
    def has_coordinates(self):
        return self.latitude is not None and self.longitude is not None


def _coordinate(value, minimum, maximum):
    if value in (None, ""):
        return None
    try:
        coordinate = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not coordinate.is_finite() or coordinate < minimum or coordinate > maximum:
        return None
    return coordinate.quantize(SIX_PLACES, rounding=ROUND_HALF_UP)


def sanitize_qrz_geography(*, grid="", latitude=None, longitude=None):
    """Validate QRZ geography and use a valid grid center as a safe fallback."""
    grid_square = normalize_maidenhead_grid(grid)
    latitude_value = _coordinate(latitude, Decimal("-90"), Decimal("90"))
    longitude_value = _coordinate(longitude, Decimal("-180"), Decimal("180"))
    if latitude_value is not None and longitude_value is not None:
        return ContactGeography(grid_square, latitude_value, longitude_value)
    if grid_square:
        center = maidenhead_to_latlon(grid_square)
        if center is not None:
            return ContactGeography(
                grid_square,
                _coordinate(center[0], Decimal("-90"), Decimal("90")),
                _coordinate(center[1], Decimal("-180"), Decimal("180")),
            )
    return ContactGeography()


def geography_payload(callsign, geography):
    return {
        "callsign": str(callsign or "").strip().upper(),
        "grid_square": geography.grid_square,
        "latitude": (
            format(geography.latitude, ".6f")
            if geography.latitude is not None
            else ""
        ),
        "longitude": (
            format(geography.longitude, ".6f")
            if geography.longitude is not None
            else ""
        ),
    }


def sign_geography(callsign, geography):
    if not geography.has_coordinates:
        return ""
    return signing.dumps(
        geography_payload(callsign, geography),
        salt=GEOGRAPHY_SIGNING_SALT,
        compress=True,
    )


def verified_geography(callsign, grid_square, latitude, longitude, token):
    if not token:
        return None
    geography = sanitize_qrz_geography(
        grid=grid_square,
        latitude=latitude,
        longitude=longitude,
    )
    if not geography.has_coordinates:
        return None
    try:
        signed_payload = signing.loads(token, salt=GEOGRAPHY_SIGNING_SALT)
    except signing.BadSignature:
        return None
    if signed_payload != geography_payload(callsign, geography):
        return None
    return geography
