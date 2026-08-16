from datetime import datetime, time
import hashlib
import json
from uuid import uuid4
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count
from django.shortcuts import redirect, render
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.auth import verified_member_or_staff_required, verified_member_required
from core.location_privacy import visible_locations
from core.models import (Adventure, JournalEntry, Location, LocationType, MemberCallsignAudit, MemberProfile,
    PotaActivationImport, PotaCallsignAttestation, PotaImportBatch)
from .pota_import import clean_pota_park_name, parse_pota_history
from .pota_parks import lookup_pota_park, normalize_pota_reference
from .pota_geocoding import entity_region, geocode_pota_park

ATTESTATION = "I confirm that I was authorized to use each listed former or alternate callsign for these activations."

def _key(token): return f"pota-import:{token}"

def _preserve_preview_form(token, payload, request):
    payload["form_values"] = {
        "import_organization": request.POST.get("import_organization", "separate"),
        "destination_choice": request.POST.get("destination_choice", ""),
        "destination_adventure": request.POST.get("destination_adventure", "").strip(),
        "new_adventure_name": request.POST.get("new_adventure_name", "").strip(),
        "new_adventure_visibility": request.POST.get("new_adventure_visibility", "public"),
    }
    cache.set(_key(token), payload, 3600)


def _selected_review_indexes(request, rows):
    """Return selected server-side row indexes from the compact review form."""
    if "selected_rows" in request.POST:
        try:
            submitted = json.loads(request.POST.get("selected_rows", ""))
        except (TypeError, ValueError):
            return None, "The selected activation list is invalid. Review the activations and try again."
        if not isinstance(submitted, list):
            return None, "The selected activation list is invalid. Review the activations and try again."
    else:
        submitted = request.POST.getlist("selected")
        if submitted == ["all"]:
            submitted = [row["index"] for row in rows if row.get("eligible", True)]
    chosen = set()
    for value in submitted:
        if isinstance(value, bool) or not str(value).isdigit():
            return None, "The selected activation list contains an invalid row identifier."
        chosen.add(int(value))
    known = {row["index"] for row in rows}
    eligible = {row["index"] for row in rows if row.get("eligible", not row.get("errors") and not row.get("duplicate") and row.get("callsign_status") != "conflict")}
    if chosen - known:
        return None, "The selected activation list contains a row that does not belong to this review batch."
    if chosen - eligible:
        return None, "The selected activation list contains a row that is not eligible for import."
    return chosen, None


def _row_visibility_overrides(request, chosen):
    if "row_visibility_overrides" in request.POST:
        try:
            submitted = json.loads(request.POST.get("row_visibility_overrides", ""))
        except (TypeError, ValueError):
            return None, "The activation visibility choices are invalid."
        if not isinstance(submitted, dict):
            return None, "The activation visibility choices are invalid."
        overrides = {}
        for key, value in submitted.items():
            if not str(key).isdigit() or int(key) not in chosen or value not in {"public", "private"}:
                return None, "The activation visibility choices contain an invalid row or value."
            overrides[int(key)] = value
        return overrides, None
    return {
        index: request.POST.get(f"row_visibility_{index}")
        for index in chosen
        if request.POST.get(f"row_visibility_{index}") in {"public", "private"}
    }, None

def _fingerprint(owner_id, row, source=PotaImportBatch.Source.ACTIVATION_HISTORY):
    if source == PotaImportBatch.Source.HUNTER_LOG:
        values = (owner_id, source, row["callsign"], row["activation_date"], row["park_reference"], row["first_qso_time"], row["last_qso_time"])
        return hashlib.sha256("|".join(str(value) for value in values).encode()).hexdigest()
    source = "|".join(str(v) for v in (owner_id, row["callsign"], row["activation_date"], row["park_reference"], row["cw"], row["data"], row["phone"], row["total"]))
    return hashlib.sha256(source.encode()).hexdigest()

def _decorate_rows(user, rows, source=PotaImportBatch.Source.ACTIVATION_HISTORY):
    current = getattr(getattr(user, "member_profile", None), "callsign", "").upper()
    former = set(MemberCallsignAudit.objects.filter(member__user=user).values_list("old_callsign", flat=True))
    others = set(MemberProfile.objects.exclude(user=user).values_list("callsign", flat=True))
    other_audits = MemberCallsignAudit.objects.exclude(member__user=user)
    others.update(other_audits.values_list("old_callsign", flat=True))
    others.update(other_audits.values_list("new_callsign", flat=True))
    seen_fingerprints = set()
    for index, row in enumerate(rows):
        row["index"] = index
        row["fingerprint"] = _fingerprint(user.pk, row, source)
        call = row["callsign"].upper()
        row["callsign_status"] = "current" if call == current else "former" if call in {x.upper() for x in former} else "conflict" if call in {x.upper() for x in others} else "attestation"
        other_source = PotaImportBatch.Source.HUNTER_LOG if source == PotaImportBatch.Source.ACTIVATION_HISTORY else PotaImportBatch.Source.ACTIVATION_HISTORY
        equivalent = PotaActivationImport.objects.filter(
            batch__owner=user, source=other_source, activation_date=row["activation_date"],
            callsign__iexact=row["callsign"], park_reference__iexact=row["park_reference"],
        ).exists()
        row["duplicate_in_review"] = row["fingerprint"] in seen_fingerprints
        seen_fingerprints.add(row["fingerprint"])
        row["duplicate"] = PotaActivationImport.objects.filter(fingerprint=row["fingerprint"]).exists() or equivalent
        reasons = list(row.get("errors") or [])
        if row["duplicate"]:
            reasons.append("Already imported")
        if row["duplicate_in_review"]:
            reasons.append("Duplicate activation in this review")
        if row["callsign_status"] == "conflict":
            reasons.append("Callsign belongs to another Radio Outdoors member")
        row["eligibility_reasons"] = reasons
        row["eligible"] = not reasons
    return rows

def _park_key(reference):
    return hashlib.sha256(normalize_pota_reference(reference).encode()).hexdigest()[:12]

def _matching_pota_location(locations, reference, clean_name, entity):
    """Apply the shared activation/Hunter Location matching order."""
    region = entity_region(entity)
    name_matches = [
        location for location in locations
        if location.name.strip().casefold() == clean_name.casefold()
        and (not region["region_code"] or location.state.strip().upper() == region["region_code"])
    ]
    reference_matches = [
        location for location in locations
        if normalize_pota_reference(location.reference_code) == reference
    ]
    matches = name_matches or reference_matches
    return matches[0] if len(matches) == 1 else None

def _unique_parks(rows, user):
    locations = list(visible_locations(user).order_by("name"))
    parks = {}
    for row in rows:
        reference = normalize_pota_reference(row["park_reference"])
        if reference not in parks:
            clean_name = clean_pota_park_name(reference, row["park_name"])
            matched = _matching_pota_location(locations, reference, clean_name, row["entity"])
            matched_location_id = (
                matched.pk
                if matched is not None
                and matched.latitude is not None
                and matched.longitude is not None
                else None
            )
            repair_location_id = (
                matched.pk
                if matched is not None
                and matched_location_id is None
                and matched.description.startswith("Created from POTA historical import.")
                else None
            )
            lookup = None if matched_location_id else lookup_pota_park(reference)
            geocode = {"status": "matched", "query": "", "candidates": []} if matched_location_id else ({"status": "found", "query": "", "candidates": [{"label": (lookup or {}).get("name") or clean_name, "provider_name": (lookup or {}).get("name") or clean_name, "latitude": lookup["latitude"], "longitude": lookup["longitude"], "match_kind": "exact"}]} if lookup else geocode_pota_park(reference, clean_name, row["entity"]))
            first_candidate = geocode["candidates"][0] if geocode.get("status") == "found" and geocode.get("candidates") else {}
            parks[reference] = {
                "key": _park_key(reference),
                "reference": reference,
                "name": clean_name,
                "display_name": f"{clean_name} — {reference}",
                "entity": (lookup or {}).get("entity") or row["entity"],
                "latitude": first_candidate.get("latitude", ""),
                "longitude": first_candidate.get("longitude", ""),
                "coordinate_quality": "Approximate park location" if first_candidate else "",
                "provider_name": first_candidate.get("provider_name", ""),
                "match_kind": first_candidate.get("match_kind", ""),
                "matched_location_id": matched_location_id,
                "repair_location_id": repair_location_id,
                "geocode_status": geocode.get("status"),
                "geocode_query": geocode.get("query", ""),
                "candidates": geocode.get("candidates", []),
                "failure_reason": geocode.get("failure_reason", ""),
                "activation_count": 0,
            }
        parks[reference]["activation_count"] += 1
    return list(parks.values())

@verified_member_required
def import_pota_history(request):
    if request.method == "POST":
        pasted = request.POST.get("pota_history", "")
        if len(pasted.encode("utf-8")) > 1_000_000:
            return render(request, "adventures/pota_history_import.html", {"error": "The pasted history is too large. Import no more than 1,000 rows at a time.", "submitted_text": pasted, "recognized_count": 0, "ignored_count": 0, "invalid_count": 0})
        try:
            parsed, ignored, invalid = parse_pota_history(pasted)
        except ValueError as exc:
            return render(request, "adventures/pota_history_import.html", {"error": str(exc), "submitted_text": pasted, "recognized_count": 0, "ignored_count": 0, "invalid_count": 0})
        if not parsed:
            return render(request, "adventures/pota_history_import.html", {"error": "No recognizable POTA activation rows were found.", "complete_failure": True, "submitted_text": pasted, "recognized_count": 0, "ignored_count": ignored, "invalid_count": len(invalid), "invalid_lines": invalid})
        rows = _decorate_rows(request.user, [row.as_dict() for row in parsed])
        parks = _unique_parks(rows, request.user)
        token = uuid4().hex
        cache.set(_key(token), {
            "owner": request.user.pk,
            "source": PotaImportBatch.Source.ACTIVATION_HISTORY,
            "rows": rows,
            "parks": parks,
            "ignored": ignored,
            "invalid": len(invalid),
            "invalid_rows": invalid,
            "submitted_text": pasted,
        }, 3600)
        return redirect("preview_pota_history", token=token)
    return render(request, "adventures/pota_history_import.html", {"submitted_text": ""})

@verified_member_required
def preview_pota_history(request, token):
    payload = cache.get(_key(token))
    if not payload or payload["owner"] != request.user.pk:
        messages.error(request, "That import preview expired. Paste the POTA history again.")
        return redirect("import_pota_history")
    locations = list(visible_locations(request.user).order_by("name"))
    parks = payload.get("parks") or _unique_parks(payload["rows"], request.user)
    for park in parks:
        park["status"] = "Existing Location matched" if park["matched_location_id"] else "Approximate pin found" if park["geocode_status"] == "found" else "Pin needs review" if park["geocode_status"] == "ambiguous" else "Lookup unavailable" if park["geocode_status"] == "unavailable" else "Pin pending"
    statuses = {park["reference"]: park["status"] for park in parks}
    for row in payload["rows"]:
        row["location_status"] = statuses.get(normalize_pota_reference(row["park_reference"]), "Pin pending")
    manageable_adventures = Adventure.objects.filter(owner=request.user)
    return render(request, "adventures/pota_history_preview.html", {"token": token, "rows": payload["rows"], "parks": parks, "ignored": payload["ignored"], "invalid_count": payload.get("invalid", 0), "invalid_rows": payload.get("invalid_rows", []), "submitted_text": payload.get("submitted_text", ""), "locations": locations, "manageable_adventures": manageable_adventures.order_by("title", "pk"), "form_values": payload.get("form_values", {}), "attestation": ATTESTATION, "needs_attestation": any(r["callsign_status"] == "attestation" and not r["errors"] and not r["duplicate"] for r in payload["rows"]), "lookup_unavailable": any(park["geocode_status"] == "unavailable" for park in parks), "existing_match_count": sum(bool(park["matched_location_id"]) for park in parks), "approximate_count": sum(bool(park["latitude"] and park["longitude"] and not park["matched_location_id"]) for park in parks), "pending_count": sum(not park["matched_location_id"] and not (park["latitude"] and park["longitude"]) for park in parks)})


@verified_member_required
@require_POST
def confirm_pota_history(request, token):
    payload = cache.get(_key(token))
    source = payload.get("source", PotaImportBatch.Source.ACTIVATION_HISTORY) if payload else PotaImportBatch.Source.ACTIVATION_HISTORY
    is_hunter = source == PotaImportBatch.Source.HUNTER_LOG
    import_route = "import_pota_hunter_log" if is_hunter else "import_pota_history"
    preview_route = "preview_pota_hunter_log" if is_hunter else "preview_pota_history"
    if not payload or payload["owner"] != request.user.pk:
        messages.error(request, "That import preview expired or was already processed.")
        return redirect(import_route)
    chosen, selection_error = _selected_review_indexes(request, payload["rows"])
    if selection_error:
        _preserve_preview_form(token, payload, request)
        messages.error(request, selection_error)
        return redirect(preview_route, token=token)
    selected = [r for r in payload["rows"] if r["index"] in chosen]
    needs_attestation = any(r["callsign_status"] == "attestation" for r in selected)
    if needs_attestation and request.POST.get("callsign_attestation") != "yes":
        _preserve_preview_form(token, payload, request)
        messages.error(request, "Confirm authorization for the listed former or alternate callsigns before importing.")
        return redirect(preview_route, token=token)
    if not selected:
        _preserve_preview_form(token, payload, request)
        messages.error(request, "Select at least one eligible activation to import.")
        return redirect(preview_route, token=token)
    visibility_overrides, visibility_error = _row_visibility_overrides(request, chosen)
    if visibility_error:
        _preserve_preview_form(token, payload, request)
        messages.error(request, visibility_error)
        return redirect(preview_route, token=token)
    organization = request.POST.get("import_organization", "separate")
    destination_choice = request.POST.get("destination_choice", "").strip()
    destination_id = request.POST.get("destination_adventure", "").strip()
    new_destination_name = request.POST.get("new_adventure_name", "").strip()
    if organization not in {"separate", "grouped"}:
        _preserve_preview_form(token, payload, request)
        messages.error(request, "Choose how the imported activations should be organized.")
        return redirect(preview_route, token=token)
    destination_adventure = None
    if organization == "grouped":
        if not destination_choice:
            destination_choice = "existing" if destination_id else "new" if new_destination_name else ""
        if destination_choice not in {"existing", "new"}:
            _preserve_preview_form(token, payload, request)
            messages.error(request, "Choose whether to use an existing Adventure or create a new Adventure.")
            return redirect(preview_route, token=token)
        if destination_id and new_destination_name:
            _preserve_preview_form(token, payload, request)
            messages.error(request, "Select an existing Adventure or enter a new Adventure name, not both.")
            return redirect(preview_route, token=token)
        if not destination_id and not new_destination_name:
            _preserve_preview_form(token, payload, request)
            messages.error(request, "Select an existing Adventure or enter a name for a new Adventure.")
            return redirect(preview_route, token=token)
        if destination_choice == "existing" and not destination_id:
            _preserve_preview_form(token, payload, request)
            messages.error(request, "Select one of your existing Adventures.")
            return redirect(preview_route, token=token)
        if destination_choice == "new" and not new_destination_name:
            _preserve_preview_form(token, payload, request)
            messages.error(request, "Enter a name for the new Adventure.")
            return redirect(preview_route, token=token)
        if destination_id:
            manageable = Adventure.objects.filter(owner=request.user)
            destination_adventure = manageable.filter(pk=destination_id).first()
            if destination_adventure is None:
                _preserve_preview_form(token, payload, request)
                messages.error(request, "You are not authorized to import into that Adventure.")
                return redirect(preview_route, token=token)
    selected_references = {normalize_pota_reference(row["park_reference"]) for row in selected}
    parks = {park["reference"]: park for park in (payload.get("parks") or _unique_parks(payload["rows"], request.user)) if park["reference"] in selected_references}
    # Historical POTA imports alone may continue with a null general pin.
    # Normal Location forms retain their existing coordinate validation.
    created, journals_created, contacts_imported, duplicate_contacts, needs_location, links = 0, 0, 0, 0, 0, []
    duplicates = sum(bool(row.get("duplicate")) for row in payload["rows"])
    with transaction.atomic():
        batch = PotaImportBatch.objects.create(owner=request.user, source=source, diagnostics={"ignored_lines": payload["ignored"], "invalid_rows": payload.get("invalid", 0), "selected_rows": len(selected), "source_qso_count": payload.get("qso_count", 0)})
        if organization == "grouped" and destination_adventure is None:
            destination_adventure = Adventure.objects.create(
                owner=request.user, title=new_destination_name,
                operating_callsign=selected[0]["callsign"], status=Adventure.Status.ACTIVE,
                is_public=request.POST.get("new_adventure_visibility", "public") == "public",
                summary="POTA activations imported as individual Journals.",
                started_at=timezone.make_aware(datetime.combine(datetime.fromisoformat(selected[-1]["activation_date"]).date(), time(12))),
            )
            created += 1
        for callsign in sorted({r["callsign"] for r in selected if r["callsign_status"] == "attestation"}):
            PotaCallsignAttestation.objects.create(batch=batch, member=request.user, callsign=callsign, attestation_text=ATTESTATION)
        resolved_locations = {}
        park_type = LocationType.objects.filter(key="park").first()
        for reference, park in parks.items():
            resolution = (
                f"existing:{park['matched_location_id']}"
                if park.get("matched_location_id")
                else f"repair:{park['repair_location_id']}"
                if park.get("repair_location_id")
                else "create"
            )
            location = None
            if resolution == "unresolved":
                resolution = "create"
            if resolution.startswith("existing:"):
                location_id = resolution.partition(":")[2]
                location = visible_locations(request.user).filter(pk=location_id).first()
            if resolution.startswith("repair:"):
                location_id = resolution.partition(":")[2]
                location = visible_locations(request.user).select_for_update().filter(
                    pk=location_id,
                    reference_code__iexact=reference,
                    description__startswith="Created from POTA historical import.",
                ).first()
            if location is None and not resolution.startswith("repair:"):
                location = visible_locations(request.user).select_for_update().filter(reference_code__iexact=reference).first()
            if location is None or resolution.startswith("repair:"):
                latitude = str(park.get("latitude") or "").strip()
                longitude = str(park.get("longitude") or "").strip()
                try:
                    latitude = Decimal(latitude) if latitude else None
                    longitude = Decimal(longitude) if longitude else None
                except InvalidOperation:
                    latitude = longitude = None
                if latitude is not None and not Decimal("-90") <= latitude <= Decimal("90"):
                    latitude = None
                if longitude is not None and not Decimal("-180") <= longitude <= Decimal("180"):
                    longitude = None
                if latitude is not None and longitude is not None and park.get("coordinate_quality"):
                    coordinate_note = "Coordinate quality: Approximate park location."
                elif latitude is not None and longitude is not None:
                    coordinate_note = "Coordinate quality: Member-placed pin supplied during POTA import review."
                else:
                    coordinate_note = "Pin needed; no coordinate was supplied by the POTA history or a configured park lookup."
                if park.get("coordinate_quality"):
                    coordinate_note = "Coordinate source: geocoded park name. Coordinate quality: approximate/general park location."
                provider_name = park.get("provider_name", "")
                provider_note = f" Provider suggestion: {provider_name}." if provider_name else ""
                description = ("Created from POTA Hunter Log import. " if is_hunter else "Created from POTA historical import. ") + coordinate_note + provider_note
                entity = park.get("entity", "")
                if location is not None:
                    location.name = park["display_name"]
                    location.latitude = latitude
                    location.longitude = longitude
                    location.state = entity.split("-", 1)[1] if entity.startswith("US-") else entity
                    location.country = "USA" if entity.startswith("US-") else ""
                    location.description = description
                    location.needs_pin_review = latitude is None or longitude is None
                    location.save(update_fields=["name", "latitude", "longitude", "state", "country", "description", "needs_pin_review"])
                else:
                    location = Location.objects.create(name=park["display_name"], created_by=request.user, visibility=Location.Visibility.PUBLIC, location_type=Location.LocationType.PARK, location_type_record=park_type, state=entity.split("-", 1)[1] if entity.startswith("US-") else entity, country="USA" if entity.startswith("US-") else "", latitude=latitude, longitude=longitude, reference_code=reference, description=description, needs_pin_review=latitude is None or longitude is None)
            resolved_locations[reference] = location
        for row in selected:
            other_source = PotaImportBatch.Source.ACTIVATION_HISTORY if is_hunter else PotaImportBatch.Source.HUNTER_LOG
            equivalent = PotaActivationImport.objects.filter(batch__owner=request.user, source=other_source, activation_date=row["activation_date"], callsign__iexact=row["callsign"], park_reference__iexact=row["park_reference"]).exists()
            if PotaActivationImport.objects.filter(fingerprint=row["fingerprint"]).exists() or equivalent:
                duplicates += 1; continue
            location = resolved_locations.get(normalize_pota_reference(row["park_reference"]))
            started = timezone.make_aware(datetime.combine(datetime.fromisoformat(row["activation_date"]).date(), time(12)))
            publication_values = request.POST.getlist("publish_pota_batch")
            batch_public = "yes" in publication_values if publication_values else True
            row_visibility = visibility_overrides.get(row["index"], "batch")
            is_public = True if row_visibility == "public" else False if row_visibility == "private" else batch_public
            summary = "Imported from POTA Hunter Log as a grouped activation session." if is_hunter else "Imported from POTA activation history. Add any Journal details or contacts you want."
            if organization == "grouped":
                adventure = destination_adventure
            else:
                adventure = Adventure.objects.create(owner=request.user, title=f"POTA Activation — {row['park_name']}", location=location, operating_callsign=row["callsign"], status=Adventure.Status.COMPLETED, is_public=is_public, summary=summary, started_at=started, completed_at=started)
                created += 1
                links.append({"title": adventure.title, "url": adventure.get_absolute_url()})
            journal = JournalEntry.objects.create(adventure=adventure, location=location, latitude=location.latitude if location else None, longitude=location.longitude if location else None, operating_callsign=row["callsign"], entry_at=started, title=f"{row['park_name']} — {row['park_reference']}", body=summary, status=JournalEntry.Status.COMPLETED, is_public=is_public, pota=True)
            journals_created += 1
            source_metadata = ({"qso_count": row["qso_count"], "bands": row["bands"], "modes": row["modes"], "first_qso_time": row["first_qso_time"], "last_qso_time": row["last_qso_time"], "session_number": row["session_number"], "source_row_ids": row["source_row_ids"], "source_line_numbers": row["source_line_numbers"], "worked_callsigns": row["worked_callsigns"]} if is_hunter else {})
            PotaActivationImport.objects.create(adventure=adventure, journal_entry=journal, batch=batch, source=source, source_metadata=source_metadata, activation_date=row["activation_date"], callsign=row["callsign"], park_reference=row["park_reference"], park_name=row["park_name"], entity=row["entity"], cw_contacts=row["cw"], data_contacts=row["data"], phone_contacts=row["phone"], total_contacts=row["total"], fingerprint=row["fingerprint"], location_resolution="unresolved" if location is None or location.needs_pin_review else "existing")
            needs_location += int(location is None or location.latitude is None or location.longitude is None)
        batch.confirmed_at = timezone.now(); batch.save(update_fields=["confirmed_at"])
    cache.delete(_key(token))
    result = {"created": created, "journals_created": journals_created, "contacts_imported": contacts_imported, "duplicate_contacts": duplicate_contacts, "duplicates": duplicates, "invalid": payload.get("invalid", 0), "needs_location": needs_location, "links": links, "destination_name": destination_adventure.title if organization == "grouped" else "", "source_label": "POTA Hunter Log" if is_hunter else "POTA Activation History"}
    request.session["pota_import_result"] = result
    if organization == "grouped":
        messages.success(request, f"POTA import complete: {journals_created} Journals created in {destination_adventure.title}; {duplicates} duplicate activations skipped; {contacts_imported} Contacts imported.")
        return redirect(destination_adventure.get_absolute_url())
    return redirect("pota_hunter_result" if is_hunter else "pota_history_result")


@verified_member_required
def pota_history_result(request):
    return render(request, "adventures/pota_history_result.html", request.session.pop("pota_import_result", {}))


def _pin_review_locations(user):
    queryset = Location.objects.filter(
        needs_pin_review=True,
        description__startswith="Created from POTA",
    )
    if not user.is_staff:
        queryset = queryset.filter(created_by=user)
    return queryset


@verified_member_or_staff_required
def pota_pin_queue(request):
    locations = _pin_review_locations(request.user).annotate(
        activation_count=Count("adventures__pota_imports", distinct=True),
    ).order_by("reference_code", "name")
    return render(request, "adventures/pota_pin_queue.html", {"locations": locations})


@verified_member_or_staff_required
@require_POST
def retry_pota_pin_lookup(request, location_id):
    location = get_object_or_404(_pin_review_locations(request.user), pk=location_id)
    activation = PotaActivationImport.objects.filter(adventure__location=location).order_by("pk").first()
    if activation is None:
        messages.error(request, "This imported park has no activation provenance available for lookup.")
        return redirect("pota_pin_queue")
    result = geocode_pota_park(
        activation.park_reference,
        clean_pota_park_name(activation.park_reference, activation.park_name),
        activation.entity,
        force_refresh=True,
    )
    candidates = result.get("candidates", [])
    if result.get("status") in {"found", "ambiguous"} and candidates:
        request.session[f"pota_pin_suggestion:{location.pk}"] = candidates[0]
        messages.success(request, "A general park-location suggestion is ready for review.")
        return redirect("review_pota_pin", location_id=location.pk)
    if result.get("status") == "unavailable":
        messages.error(request, "Automatic park-location lookup is currently unavailable. You may place the pin manually.")
    else:
        messages.error(request, "No general park-location suggestion was found. You may place the pin manually.")
    return redirect("review_pota_pin", location_id=location.pk)


@verified_member_or_staff_required
def review_pota_pin(request, location_id):
    location = get_object_or_404(_pin_review_locations(request.user), pk=location_id)
    if request.method == "POST":
        existing_id = request.POST.get("existing_location", "").strip()
        if existing_id:
            existing = visible_locations(request.user).exclude(pk=location.pk).filter(pk=existing_id).first()
            if existing is None:
                messages.error(request, "Choose an available existing Location.")
            else:
                location.adventures.filter(pota_imports__isnull=False).update(location=existing)
                if not location.adventures.exists():
                    location.delete()
                messages.success(request, "Imported activations now use the selected existing Location.")
                return redirect("pota_pin_queue")
        else:
            try:
                latitude = Decimal(request.POST.get("latitude", "").strip())
                longitude = Decimal(request.POST.get("longitude", "").strip())
                valid = Decimal("-90") <= latitude <= Decimal("90") and Decimal("-180") <= longitude <= Decimal("180")
            except (InvalidOperation, ValueError):
                valid = False
            if valid:
                suggestion = request.session.pop(f"pota_pin_suggestion:{location.pk}", {})
                provider_name = suggestion.get("provider_name", "")
                location.latitude = latitude
                location.longitude = longitude
                location.needs_pin_review = False
                location.description = (
                    "Created from POTA historical import. Coordinate source: POTA park pin review. "
                    "Coordinate quality: approximate/general park location."
                    + (f" Provider suggestion: {provider_name}." if provider_name else "")
                )
                location.save(update_fields=["latitude", "longitude", "needs_pin_review", "description"])
                messages.success(request, "The general park pin was saved and is now available on the Map.")
                return redirect("pota_pin_queue")
            messages.error(request, "Place Pin before saving this park Location.")
    suggestion = request.session.get(f"pota_pin_suggestion:{location.pk}", {})
    return render(request, "adventures/pota_pin_review.html", {
        "location": location,
        "suggestion": suggestion,
        "initial_latitude": suggestion.get("latitude", location.latitude or ""),
        "initial_longitude": suggestion.get("longitude", location.longitude or ""),
        "existing_locations": visible_locations(request.user).exclude(pk=location.pk).filter(
            latitude__isnull=False, longitude__isnull=False
        ).order_by("name"),
    })
