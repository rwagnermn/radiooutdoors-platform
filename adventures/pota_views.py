from datetime import datetime, time
import hashlib
import re
from uuid import uuid4
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.cache import cache
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.auth import verified_member_required
from core.location_privacy import visible_locations
from core.models import (Adventure, Location, LocationType, MemberCallsignAudit, MemberProfile,
    PotaActivationImport, PotaCallsignAttestation, PotaImportBatch)
from .pota_import import parse_pota_history
from .pota_parks import lookup_pota_park, normalize_pota_reference
from .pota_geocoding import entity_region, geocode_pota_park

ATTESTATION = "I confirm that I was authorized to use each listed former or alternate callsign for these activations."

def _key(token): return f"pota-import:{token}"

def _fingerprint(owner_id, row):
    source = "|".join(str(v) for v in (owner_id, row["callsign"], row["activation_date"], row["park_reference"], row["cw"], row["data"], row["phone"], row["total"]))
    return hashlib.sha256(source.encode()).hexdigest()

def _decorate_rows(user, rows):
    current = getattr(getattr(user, "member_profile", None), "callsign", "").upper()
    former = set(MemberCallsignAudit.objects.filter(member__user=user).values_list("old_callsign", flat=True))
    others = set(MemberProfile.objects.exclude(user=user).values_list("callsign", flat=True))
    other_audits = MemberCallsignAudit.objects.exclude(member__user=user)
    others.update(other_audits.values_list("old_callsign", flat=True))
    others.update(other_audits.values_list("new_callsign", flat=True))
    for index, row in enumerate(rows):
        row["index"] = index
        row["fingerprint"] = _fingerprint(user.pk, row)
        call = row["callsign"].upper()
        row["callsign_status"] = "current" if call == current else "former" if call in {x.upper() for x in former} else "conflict" if call in {x.upper() for x in others} else "attestation"
        row["duplicate"] = PotaActivationImport.objects.filter(fingerprint=row["fingerprint"]).exists()
    return rows

def _park_key(reference):
    return hashlib.sha256(normalize_pota_reference(reference).encode()).hexdigest()[:12]

def _clean_park_name(reference, name):
    prefix = rf"^{re.escape(normalize_pota_reference(reference))}\s*[\-\u2013\u2014:]\s*"
    return re.sub(prefix, "", (name or "").strip(), flags=re.IGNORECASE).strip()

def _unique_parks(rows, user):
    locations = list(visible_locations(user).order_by("name"))
    parks = {}
    for row in rows:
        reference = normalize_pota_reference(row["park_reference"])
        if reference not in parks:
            clean_name = _clean_park_name(reference, row["park_name"])
            row_region = entity_region(row["entity"])
            reference_matches = [loc for loc in locations if normalize_pota_reference(loc.reference_code) == reference]
            name_matches = [loc for loc in locations if loc.name.strip().casefold() == clean_name.casefold() and (not row_region["region_code"] or loc.state.strip().upper() == row_region["region_code"])]
            matched = (reference_matches or name_matches)
            matched_location_id = matched[0].pk if len(matched) == 1 else None
            lookup = None if matched_location_id else lookup_pota_park(reference)
            geocode = {"status": "matched", "query": "", "candidates": []} if matched_location_id else ({"status": "found", "query": "", "candidates": [{"label": (lookup or {}).get("name") or clean_name, "latitude": lookup["latitude"], "longitude": lookup["longitude"]}]} if lookup else geocode_pota_park(reference, clean_name, row["entity"]))
            first_candidate = geocode["candidates"][0] if geocode.get("status") == "found" and geocode.get("candidates") else {}
            parks[reference] = {
                "key": _park_key(reference),
                "reference": reference,
                "name": (lookup or {}).get("name") or clean_name,
                "entity": (lookup or {}).get("entity") or row["entity"],
                "latitude": first_candidate.get("latitude", ""),
                "longitude": first_candidate.get("longitude", ""),
                "coordinate_quality": "Approximate park location" if first_candidate else "",
                "matched_location_id": matched_location_id,
                "geocode_status": geocode.get("status"),
                "geocode_query": geocode.get("query", ""),
                "candidates": geocode.get("candidates", []),
            }
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
        if invalid:
            return render(request, "adventures/pota_history_import.html", {"error": "Some activation rows could not be recognized. Correct the listed lines and review again.", "submitted_text": pasted, "recognized_count": len(parsed), "ignored_count": ignored, "invalid_count": len(invalid), "invalid_lines": invalid})
        if not parsed:
            return render(request, "adventures/pota_history_import.html", {"error": "No recognizable POTA activation rows were found.", "complete_failure": True, "submitted_text": pasted, "recognized_count": 0, "ignored_count": ignored, "invalid_count": 0})
        rows = _decorate_rows(request.user, [row.as_dict() for row in parsed])
        parks = _unique_parks(rows, request.user)
        token = uuid4().hex
        cache.set(_key(token), {"owner": request.user.pk, "rows": rows, "parks": parks, "ignored": ignored}, 3600)
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
        park["status"] = "Matched existing Location" if park["matched_location_id"] else "Approximate park location found" if park["geocode_status"] == "found" else "Multiple possible Locations—review" if park["geocode_status"] == "ambiguous" else "Location not found—place pin"
    return render(request, "adventures/pota_history_preview.html", {"token": token, "rows": payload["rows"], "parks": parks, "ignored": payload["ignored"], "locations": locations, "attestation": ATTESTATION, "needs_attestation": any(r["callsign_status"] == "attestation" and not r["errors"] and not r["duplicate"] for r in payload["rows"])})

@verified_member_required
@require_POST
def confirm_pota_history(request, token):
    payload = cache.get(_key(token))
    if not payload or payload["owner"] != request.user.pk:
        messages.error(request, "That import preview expired or was already processed.")
        return redirect("import_pota_history")
    chosen = {int(x) for x in request.POST.getlist("selected") if x.isdigit()}
    selected = [r for r in payload["rows"] if r["index"] in chosen and not r["errors"] and not r["duplicate"] and r["callsign_status"] != "conflict"]
    needs_attestation = any(r["callsign_status"] == "attestation" for r in selected)
    if needs_attestation and request.POST.get("callsign_attestation") != "yes":
        messages.error(request, "Confirm authorization for the listed former or alternate callsigns before importing.")
        return redirect("preview_pota_history", token=token)
    if not selected:
        messages.error(request, "Select at least one eligible activation to import.")
        return redirect("preview_pota_history", token=token)
    selected_references = {normalize_pota_reference(row["park_reference"]) for row in selected}
    parks = {park["reference"]: park for park in (payload.get("parks") or _unique_parks(payload["rows"], request.user)) if park["reference"] in selected_references}
    created, duplicates, needs_location, links = 0, 0, 0, []
    with transaction.atomic():
        batch = PotaImportBatch.objects.create(owner=request.user, diagnostics={"ignored_lines": payload["ignored"], "selected_rows": len(selected)})
        for callsign in sorted({r["callsign"] for r in selected if r["callsign_status"] == "attestation"}):
            PotaCallsignAttestation.objects.create(batch=batch, member=request.user, callsign=callsign, attestation_text=ATTESTATION)
        resolved_locations = {}
        park_type = LocationType.objects.filter(key="park").first()
        for reference, park in parks.items():
            key = park["key"]
            resolution = request.POST.get(f"park_resolution_{key}", "create")
            location = None
            if resolution == "unresolved":
                resolved_locations[reference] = None
                continue
            if resolution.startswith("existing:"):
                location_id = resolution.partition(":")[2]
                location = visible_locations(request.user).filter(pk=location_id).first()
            if location is None:
                location = visible_locations(request.user).select_for_update().filter(reference_code__iexact=reference).first()
            if location is None:
                latitude = request.POST.get(f"park_latitude_{key}", "").strip()
                longitude = request.POST.get(f"park_longitude_{key}", "").strip()
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
                description = "Created from POTA historical import. " + coordinate_note
                entity = park.get("entity", "")
                location = Location.objects.create(name=park["name"], created_by=request.user, visibility=Location.Visibility.PRIVATE if request.POST.get(f"park_private_{key}") == "yes" else Location.Visibility.PUBLIC, location_type=Location.LocationType.PARK, location_type_record=park_type, state=entity.split("-", 1)[1] if entity.startswith("US-") else entity, country="USA" if entity.startswith("US-") else "", latitude=latitude, longitude=longitude, reference_code=reference, description=description)
            resolved_locations[reference] = location
        for row in selected:
            if PotaActivationImport.objects.filter(fingerprint=row["fingerprint"]).exists():
                duplicates += 1; continue
            location = resolved_locations.get(normalize_pota_reference(row["park_reference"]))
            started = timezone.make_aware(datetime.combine(datetime.fromisoformat(row["activation_date"]).date(), time(12)))
            adventure = Adventure.objects.create(owner=request.user, title=f"POTA Activation — {row['park_name']}", location=location, operating_callsign=row["callsign"], status=Adventure.Status.COMPLETED, is_public=False, summary="Imported from POTA activation history. Review this private Adventure, add any Journal details or contacts you want, then publish it when ready.", started_at=started, completed_at=started)
            PotaActivationImport.objects.create(adventure=adventure, batch=batch, activation_date=row["activation_date"], callsign=row["callsign"], park_reference=row["park_reference"], park_name=row["park_name"], entity=row["entity"], cw_contacts=row["cw"], data_contacts=row["data"], phone_contacts=row["phone"], total_contacts=row["total"], fingerprint=row["fingerprint"], location_resolution="existing" if location else "unresolved")
            created += 1; needs_location += int(location is None or location.latitude is None or location.longitude is None); links.append({"title": adventure.title, "url": adventure.get_absolute_url()})
        batch.confirmed_at = timezone.now(); batch.save(update_fields=["confirmed_at"])
    cache.delete(_key(token))
    request.session["pota_import_result"] = {"created": created, "duplicates": duplicates, "needs_location": needs_location, "links": links}
    return redirect("pota_history_result")

@verified_member_required
def pota_history_result(request):
    return render(request, "adventures/pota_history_result.html", request.session.pop("pota_import_result", {}))
