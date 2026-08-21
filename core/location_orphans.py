from dataclasses import dataclass

from django.db import transaction
from django.db.models import Count

from .models import Location


class OrphanLocationSafetyError(RuntimeError):
    pass


@dataclass(frozen=True)
class OrphanLocationResult:
    ids: tuple[int, ...]
    deleted_locations: int
    deleted_related_operating_locations: int


def orphan_locations():
    """Locations unused by every Journal, using the same count shown as Uses."""
    return Location.objects.annotate(
        journal_usage_count=Count("journal_entries", distinct=True)
    ).filter(journal_usage_count=0)


def delete_orphan_locations() -> OrphanLocationResult:
    """Delete only zero-Journal Locations after checking other live references."""
    with transaction.atomic():
        candidates = list(
            orphan_locations().select_for_update().order_by("pk")
        )
        unsafe = []
        for location in candidates:
            reasons = []
            if location.adventures.exists():
                reasons.append("Adventure reference")
            if location.contacts.exists():
                reasons.append("Contact reference")
            if location.operating_locations.filter(adventures__isnull=False).exists():
                reasons.append("Adventure-used operating position")
            if reasons:
                unsafe.append(f"{location.pk}: {', '.join(reasons)}")
        if unsafe:
            raise OrphanLocationSafetyError(
                "Refusing orphan cleanup because other records require preservation: "
                + "; ".join(unsafe)
            )

        ids = tuple(location.pk for location in candidates)
        if not ids:
            return OrphanLocationResult((), 0, 0)
        _, breakdown = Location.objects.filter(pk__in=ids).delete()
        return OrphanLocationResult(
            ids=ids,
            deleted_locations=breakdown.get("core.Location", 0),
            deleted_related_operating_locations=breakdown.get(
                "core.OperatingLocation", 0
            ),
        )
