from datetime import date, time
import hashlib
from uuid import uuid4

from django.contrib import messages
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from core.auth import verified_member_or_staff_required, verified_member_required
from core.location_privacy import visible_locations
from core.models import Adventure, JournalContact, JournalEntry, Location, LocationType
from .adif_parser import haversine_miles
from .forms import JournalContactForm
from .pota_geocoding import entity_region
from .pota_import import clean_pota_park_name, parse_pota_hunter_log
from .pota_parks import normalize_pota_reference
from .pota_views import _matching_pota_location, _unique_parks


def _hunter_key(token):
    return f"pota-hunter-contacts:{token}"


def _hunter_fingerprint(owner_id, row):
    values = (
        owner_id, row["activation_date"], row["qso_at"].time().isoformat(),
        row["station_callsign"], row["operator_callsign"], row["worked_callsign"],
        row["band"], row["mode"], row["park_reference"],
    )
    return hashlib.sha256("|".join(str(value).upper() for value in values).encode()).hexdigest()


def _owned_contacts(user):
    return JournalContact.objects.filter(
        Q(owner=user) | Q(owner__isnull=True, journal_entry__adventure__owner=user)
    )


def _owned_journals(user):
    journals = JournalEntry.objects.all() if user.is_staff else JournalEntry.objects.filter(adventure__owner=user)
    return journals.select_related("adventure").order_by(
        "-entry_at", "-pk"
    )


def _owned_adventures(user):
    adventures = Adventure.objects.all() if user.is_staff else Adventure.objects.filter(owner=user)
    return adventures.order_by("title", "pk")


def _requested_journal(user, value):
    if not value:
        return None
    return get_object_or_404(_owned_journals(user), pk=value)


def _resolve_hunter_locations(user, parks):
    """Create/reuse Locations from the activation importer's park-resolution results."""
    resolved = {}
    park_type = LocationType.objects.filter(key="park").first()
    for park in parks:
        reference = normalize_pota_reference(park["reference"])
        region = entity_region(park.get("entity", ""))
        clean_name = clean_pota_park_name(reference, park.get("name", ""))
        locations = visible_locations(user).select_for_update()
        location = _matching_pota_location(
            list(locations.order_by("name")), reference, clean_name, park.get("entity", "")
        )
        latitude, longitude = park.get("latitude"), park.get("longitude")
        if location is None and latitude not in (None, "") and longitude not in (None, ""):
            provider = park.get("provider_name", "")
            provider_note = f" Provider suggestion: {provider}." if provider else ""
            location = Location.objects.create(
                name=clean_name,
                created_by=user,
                visibility=Location.Visibility.PRIVATE,
                location_type=Location.LocationType.PARK,
                location_type_record=park_type,
                state=region["region_code"],
                country="USA" if region["country_code"] == "US" else region["country_name"],
                latitude=latitude,
                longitude=longitude,
                reference_code=reference,
                description=(
                    "Created from POTA Hunter Log import. Coordinate source: geocoded park name. "
                    "Coordinate quality: approximate/general park location." + provider_note
                ),
                needs_pin_review=False,
            )
        resolved[reference] = location
    return resolved


def _hunter_distance_miles(destination, resolved_location):
    origin = destination.adventure.location if destination else None
    if not origin or not resolved_location:
        return None
    coordinates = (
        origin.latitude, origin.longitude,
        resolved_location.latitude, resolved_location.longitude,
    )
    if any(value is None for value in coordinates):
        return None
    return round(haversine_miles(*(float(value) for value in coordinates)))


@verified_member_required
def my_contact_log(request):
    contacts = _owned_contacts(request.user).select_related("adventure", "journal_entry__adventure", "resolved_location")
    if request.GET.get("date_from"):
        contacts = contacts.filter(qso_date__gte=request.GET["date_from"])
    if request.GET.get("date_to"):
        contacts = contacts.filter(qso_date__lte=request.GET["date_to"])
    if request.GET.get("callsign"):
        value = request.GET["callsign"].strip()
        contacts = contacts.filter(Q(callsign__icontains=value) | Q(station_callsign__icontains=value) | Q(operator_callsign__icontains=value))
    for field in ("band", "mode", "source"):
        if request.GET.get(field):
            contacts = contacts.filter(**{f"{field}__iexact": request.GET[field].strip()})
    if request.GET.get("park"):
        contacts = contacts.filter(pota_park_reference__icontains=request.GET["park"].strip())
    association = request.GET.get("association")
    if association == "associated":
        contacts = contacts.filter(Q(adventure__isnull=False) | Q(journal_entry__isnull=False))
    elif association == "unassociated":
        contacts = contacts.filter(adventure__isnull=True, journal_entry__isnull=True)
    return render(request, "adventures/contact_log.html", {
        "contacts": contacts.order_by("-qso_date", "-time_on", "-pk"),
        "source_choices": JournalContact.Source.choices,
    })


@verified_member_required
@require_POST
def bulk_delete_contacts(request):
    selected_ids = [value for value in request.POST.getlist("contact_ids") if value.isdigit()]
    contacts = _owned_contacts(request.user).filter(pk__in=selected_ids).order_by("pk")
    if not selected_ids or not contacts.exists():
        messages.info(request, "No owned Contacts were selected.")
        return redirect("my_contact_log")
    if request.POST.get("confirm_delete") == "1":
        deleted_count = contacts.count()
        contacts.delete()
        messages.success(request, f"{deleted_count} selected Contact{'s' if deleted_count != 1 else ''} deleted.")
        return redirect("my_contact_log")
    return render(request, "adventures/contact_bulk_delete_confirm.html", {
        "contacts": contacts,
        "contact_ids": list(contacts.values_list("pk", flat=True)),
        "selected_count": contacts.count(),
    })


@verified_member_or_staff_required
def import_pota_hunter_contacts(request):
    destination = _requested_journal(
        request.user,
        request.POST.get("journal_entry") or request.GET.get("journal_entry"),
    )
    destination_context = {
        "destination_journal": destination,
        "adventures": _owned_adventures(request.user),
        "journals": _owned_journals(request.user),
    }
    if request.method == "POST":
        pasted = request.POST.get("pota_hunter_log", "")
        adventure_id = request.POST.get("adventure")
        if adventure_id and destination is None:
            return render(request, "adventures/pota_hunter_import.html", {
                "error": "Select a Journal for the selected Adventure, or leave both destinations blank.",
                "submitted_text": pasted, "adventures": _owned_adventures(request.user),
                "journals": _owned_journals(request.user), "selected_adventure_id": adventure_id,
            })
        if adventure_id and str(destination.adventure_id) != str(adventure_id):
            return render(request, "adventures/pota_hunter_import.html", {
                "error": "The selected Journal does not belong to the selected Adventure.",
                "submitted_text": pasted, "adventures": _owned_adventures(request.user),
                "journals": _owned_journals(request.user), "selected_adventure_id": adventure_id,
            })
        try:
            parsed, ignored, invalid = parse_pota_hunter_log(pasted)
        except ValueError as exc:
            return render(request, "adventures/pota_hunter_import.html", {**destination_context, "error": str(exc), "submitted_text": pasted})
        if invalid:
            return render(request, "adventures/pota_hunter_import.html", {**destination_context, "error": "Some Hunter Log rows could not be recognized.", "submitted_text": pasted, "recognized_count": len(parsed), "ignored_count": ignored, "invalid_count": len(invalid), "invalid_lines": invalid})
        if not parsed:
            return render(request, "adventures/pota_hunter_import.html", {**destination_context, "error": "No Hunter record boundary or structured Hunter Log header with the required fields was recognized.", "submitted_text": pasted, "recognized_count": 0, "ignored_count": ignored, "invalid_count": 0, "unrecognized_excerpt": " ".join(pasted.split())[:180]})
        existing = set(_owned_contacts(request.user).filter(source=JournalContact.Source.POTA_HUNTER).values_list("fingerprint", flat=True))
        rows = []
        for index, row in enumerate(parsed):
            serialized = {**row, "index": index, "qso_at": row["qso_at"].isoformat()}
            serialized["fingerprint"] = _hunter_fingerprint(request.user.pk, row)
            serialized["duplicate"] = serialized["fingerprint"] in existing
            rows.append(serialized)
        parks = _unique_parks(rows, request.user)
        park_statuses = {
            park["reference"]: bool(park.get("matched_location_id") or (
                park.get("latitude") not in (None, "") and park.get("longitude") not in (None, "")
            )) for park in parks
        }
        for row in rows:
            row["has_pin"] = park_statuses.get(normalize_pota_reference(row["park_reference"]), False)
        token = uuid4().hex
        cache.set(_hunter_key(token), {"owner": request.user.pk, "rows": rows, "parks": parks, "ignored": ignored, "invalid": len(invalid), "journal_entry": destination.pk if destination else None}, 3600)
        return redirect("preview_pota_hunter_log", token=token)
    return render(request, "adventures/pota_hunter_import.html", {**destination_context, "submitted_text": ""})


@verified_member_or_staff_required
def preview_pota_hunter_contacts(request, token):
    payload = cache.get(_hunter_key(token))
    if not payload or payload["owner"] != request.user.pk:
        messages.error(request, "That Hunter Log preview expired.")
        return redirect("import_pota_hunter_log")
    destination = _requested_journal(request.user, payload.get("journal_entry"))
    return render(request, "adventures/pota_hunter_contact_preview.html", {"token": token, **payload, "destination_journal": destination, "duplicate_count": sum(row["duplicate"] for row in payload["rows"]), "no_pin_count": sum(not row.get("has_pin", False) for row in payload["rows"])})


@verified_member_or_staff_required
@require_POST
def confirm_pota_hunter_contacts(request, token):
    payload = cache.get(_hunter_key(token))
    if not payload or payload["owner"] != request.user.pk:
        messages.error(request, "That Hunter Log preview expired.")
        return redirect("import_pota_hunter_log")
    selected_values = request.POST.getlist("selected")
    # Destination is fixed at preview creation; confirmation cannot drop or replace it.
    destination = _requested_journal(request.user, payload.get("journal_entry"))
    selected = ({row["index"] for row in payload["rows"]} if "all" in selected_values else {int(value) for value in selected_values if value.isdigit()})
    existing = set(_owned_contacts(request.user).filter(source=JournalContact.Source.POTA_HUNTER).values_list("fingerprint", flat=True))
    pending, duplicates = [], 0
    importable_references = {
        normalize_pota_reference(row["park_reference"])
        for row in payload["rows"]
        if row["index"] in selected and row["fingerprint"] not in existing
    }
    selected_parks = [
        park for park in payload.get("parks", [])
        if normalize_pota_reference(park["reference"]) in importable_references
    ]
    with transaction.atomic():
        resolved_locations = _resolve_hunter_locations(request.user, selected_parks)
        for row in payload["rows"]:
            if row["index"] not in selected:
                continue
            if row["fingerprint"] in existing:
                duplicates += 1
                continue
            mode_text = row["mode"]
            mode, submode = mode_text, ""
            if "(" in mode_text and mode_text.endswith(")"):
                mode, submode = mode_text.split("(", 1)
                mode, submode = mode.strip(), submode[:-1].strip()
            qso_at = row["qso_at"]
            resolved_location = resolved_locations.get(normalize_pota_reference(row["park_reference"]))
            pending.append(JournalContact(
                owner=request.user, journal_entry=destination,
                adventure=destination.adventure if destination else None,
                qso_date=date.fromisoformat(row["activation_date"]),
                time_on=time.fromisoformat(qso_at.split("T", 1)[1]),
                station_callsign=row["station_callsign"], operator_callsign=row["operator_callsign"],
                callsign=row["worked_callsign"], band=row["band"], mode=mode, submode=submode,
                state=row["entity"], pota_park_reference=row["park_reference"], pota_park_name=row["park_name"],
                is_p2p=row.get("is_p2p", False),
                resolved_location=resolved_location,
                distance_miles=_hunter_distance_miles(destination, resolved_location),
                source=JournalContact.Source.POTA_HUNTER, fingerprint=row["fingerprint"],
            ))
            existing.add(row["fingerprint"])
        JournalContact.objects.bulk_create(pending, batch_size=1000)
    cache.delete(_hunter_key(token))
    no_pin_count = sum(contact.resolved_location is None for contact in pending)
    messages.success(request, f"{len(pending)} Hunter Log contact{'s' if len(pending) != 1 else ''} imported; {no_pin_count} No Pin.")
    if duplicates:
        messages.info(request, f"{duplicates} duplicate contact{'s' if duplicates != 1 else ''} skipped.")
    if destination:
        return redirect("journal_entry_detail", entry_id=destination.pk)
    return redirect("my_contact_log")


@verified_member_required
def pota_hunter_contact_result(request):
    return redirect("my_contact_log")


@verified_member_or_staff_required
def add_journal_contact(request, entry_id):
    entry = get_object_or_404(JournalEntry.objects.select_related("adventure__owner"), pk=entry_id)
    if request.user != entry.adventure.owner and not request.user.is_staff:
        return HttpResponseForbidden("Only the Adventure owner or staff can add Contacts to this Journal.")
    if request.method == "POST":
        form = JournalContactForm(request.POST)
        if form.is_valid():
            contact = form.save(commit=False)
            contact.owner = entry.adventure.owner
            contact.adventure = entry.adventure
            contact.journal_entry = entry
            contact.source = JournalContact.Source.MANUAL
            contact.station_callsign = entry.operating_callsign or entry.adventure.operating_callsign
            contact.operator_callsign = entry.operating_callsign or entry.adventure.operating_callsign
            contact.fingerprint = hashlib.sha256(f"manual|{entry.pk}|{uuid4().hex}".encode()).hexdigest()
            contact.save()
            entry.adventure.save(update_fields=["updated_at"])
            messages.success(request, "Contact added to this Journal.")
            return redirect("journal_entry_detail", entry_id=entry.pk)
    else:
        form = JournalContactForm(initial={"qso_date": entry.entry_at.date()})
    return render(request, "adventures/add_journal_contact.html", {"entry": entry, "adventure": entry.adventure, "form": form})
