from datetime import date, time
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.auth import verified_member_required

from core.models import JournalContact, JournalEntry

from .adif_parser import parse_adif_bytes
from .forms import AdifImportForm


def _entry_origin(entry):
    operating_location = entry.adventure.operating_location
    location = entry.adventure.location

    if (
        operating_location
        and operating_location.latitude is not None
        and operating_location.longitude is not None
    ):
        return (
            float(operating_location.latitude),
            float(operating_location.longitude),
        )

    if (
        location
        and location.latitude is not None
        and location.longitude is not None
    ):
        return (
            float(location.latitude),
            float(location.longitude),
        )

    return (None, None)


def _preview_path(token):
    directory = Path(settings.MEDIA_ROOT) / "adif_import_previews"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{token}.json"


def _contact_fingerprint(contact):
    source = "|".join(
        [
            contact["qso_date"],
            contact.get("time_on", ""),
            contact["callsign"].upper(),
            contact.get("mode", "").upper(),
        ]
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _owned_entry(request, entry_id):
    entry = get_object_or_404(
        JournalEntry.objects.select_related(
            "adventure",
            "adventure__location",
            "adventure__operating_location",
        ),
        pk=entry_id,
    )

    if entry.adventure.owner != request.user:
        return None, HttpResponseForbidden(
            "Only the Adventure owner can import contacts."
        )

    return entry, None


@verified_member_required
def import_adif(request, entry_id):
    entry, forbidden = _owned_entry(request, entry_id)

    if forbidden:
        return forbidden

    if request.method == "POST":
        form = AdifImportForm(request.POST, request.FILES)

        if form.is_valid():
            uploaded_file = form.cleaned_data["adif_file"]
            latitude, longitude = _entry_origin(entry)
            contacts = parse_adif_bytes(
                uploaded_file.read(),
                origin_latitude=latitude,
                origin_longitude=longitude,
            )

            if not contacts:
                form.add_error(
                    "adif_file",
                    "No valid contacts with callsign and QSO date were found.",
                )
            else:
                token = uuid4().hex
                payload = {
                    "entry_id": entry.pk,
                    "filename": uploaded_file.name,
                    "contacts": [contact.as_dict() for contact in contacts],
                }

                _preview_path(token).write_text(
                    json.dumps(payload),
                    encoding="utf-8",
                )
                request.session["adif_preview_token"] = token

                return redirect(
                    "preview_adif_import",
                    entry_id=entry.pk,
                    token=token,
                )
    else:
        form = AdifImportForm()

    return render(
        request,
        "adventures/import_adif.html",
        {
            "entry": entry,
            "adventure": entry.adventure,
            "form": form,
        },
    )


@verified_member_required
def preview_adif_import(request, entry_id, token):
    entry, forbidden = _owned_entry(request, entry_id)

    if forbidden:
        return forbidden

    if request.session.get("adif_preview_token") != token:
        messages.error(request, "That ADIF preview has expired.")
        return redirect("import_adif", entry_id=entry.pk)

    path = _preview_path(token)

    if not path.exists():
        messages.error(request, "That ADIF preview has expired.")
        return redirect("import_adif", entry_id=entry.pk)

    payload = json.loads(path.read_text(encoding="utf-8"))
    contacts = payload["contacts"]
    dates = [contact["qso_date"] for contact in contacts]
    modes = sorted(
        {
            contact["mode"]
            for contact in contacts
            if contact.get("mode")
        }
    )

    return render(
        request,
        "adventures/preview_adif_import.html",
        {
            "entry": entry,
            "adventure": entry.adventure,
            "token": token,
            "filename": payload["filename"],
            "contact_count": len(contacts),
            "date_start": min(dates),
            "date_end": max(dates),
            "modes": modes,
            "preview_contacts": contacts[:12],
        },
    )


@verified_member_required
@require_POST
def confirm_adif_import(request, entry_id, token):
    entry, forbidden = _owned_entry(request, entry_id)

    if forbidden:
        return forbidden

    if request.session.get("adif_preview_token") != token:
        messages.error(request, "That ADIF preview has expired.")
        return redirect("import_adif", entry_id=entry.pk)

    path = _preview_path(token)

    if not path.exists():
        messages.error(request, "That ADIF preview has expired.")
        return redirect("import_adif", entry_id=entry.pk)

    payload = json.loads(path.read_text(encoding="utf-8"))
    duplicate_count = 0

    with transaction.atomic():
        existing = set(
            entry.contacts.values_list("fingerprint", flat=True)
        )
        pending = []

        for contact in payload["contacts"]:
            fingerprint = _contact_fingerprint(contact)

            if fingerprint in existing:
                duplicate_count += 1
                continue

            pending.append(
                JournalContact(
                    journal_entry=entry,
                    qso_date=date.fromisoformat(contact["qso_date"]),
                    time_on=(
                        time.fromisoformat(contact["time_on"])
                        if contact.get("time_on")
                        else None
                    ),
                    callsign=contact["callsign"],
                    mode=contact.get("mode", ""),
                    name=contact.get("name", ""),
                    state=contact.get("state", ""),
                    country=contact.get("country", ""),
                    distance_miles=contact.get("distance_miles"),
                    comment=contact.get("comment", ""),
                    grid_square=contact.get("grid_square", ""),
                    fingerprint=fingerprint,
                )
            )
            existing.add(fingerprint)

        JournalContact.objects.bulk_create(
            pending,
            batch_size=1000,
        )

    path.unlink(missing_ok=True)
    request.session.pop("adif_preview_token", None)
    entry.adventure.save(update_fields=["updated_at"])

    messages.success(
        request,
        f"{len(pending)} contact{'s' if len(pending) != 1 else ''} imported.",
    )

    if duplicate_count:
        messages.info(
            request,
            (
                f"{duplicate_count} duplicate contact"
                f"{'s were' if duplicate_count != 1 else ' was'} skipped."
            ),
        )

    return redirect("journal_entry_detail", entry_id=entry.pk)


@verified_member_required
@require_POST
def cancel_adif_import(request, entry_id, token):
    entry, forbidden = _owned_entry(request, entry_id)

    if forbidden:
        return forbidden

    _preview_path(token).unlink(missing_ok=True)
    request.session.pop("adif_preview_token", None)
    return redirect("import_adif", entry_id=entry.pk)
