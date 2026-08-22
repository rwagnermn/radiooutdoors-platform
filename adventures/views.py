from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone

from PIL import Image
from datetime import date, datetime, time
import hashlib
import json
import logging
import random
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from core.models import (
    Adventure, AdventureCoverSelectionAudit, Comment, JournalContact,
    JournalEntry, Location, OperatingLocation, Photo,
)
from core.photo_moderation import moderate_location_photo, moderate_photo
from core.photo_upload_notices import add_photo_upload_notice
from core.form_validation import form_error_payload, validation_error_payload
from core.pin_permissions import can_edit_location_pin, can_edit_operating_position_pin
from core.location_privacy import (
    can_manage_location, can_view_location, location_access_q,
    mark_adventure_location_visibility, visible_locations,
)
from core.auth import (
    is_verified_member,
    verified_member_or_staff_required,
    verified_member_required,
)

from .adif_parser import parse_adif_bytes_with_counts
from .contact_map import build_adventure_contact_map, build_contact_map
from .pota_aggregation import aggregate_pota_journals
from .pota_aggregation import eligible_pota_journal_imports

from .forms import (
    AdifImportForm,
    AdventureForm,
    CommentForm,
    JournalEntryForm,
    LocationForm,
    OperatingLocationForm,
)


logger = logging.getLogger(__name__)


PENDING_JOURNAL_BULK_DELETE_SESSION_KEY = "pending_journal_bulk_delete"


def _safe_external_reference_url(value):
    reference = (value or "").strip()
    if not reference:
        return ""
    try:
        URLValidator(schemes=["http", "https"])(reference)
    except ValidationError:
        return ""
    return reference

def _journal_location_choices(user):
    return [
        {"id": item.pk, "name": item.name,
         "latitude": float(item.latitude) if item.latitude is not None else None,
         "longitude": float(item.longitude) if item.longitude is not None else None}
        for item in visible_locations(user).order_by("name")
    ]


def _journal_map_defaults(adventure, user, exclude_entry=None):
    recent = adventure.journal_entries.exclude(
        latitude__isnull=True, longitude__isnull=True
    )
    if exclude_entry is not None:
        recent = recent.exclude(pk=exclude_entry.pk)
    recent = recent.order_by("-entry_at", "-pk").first()
    nearby_locations = visible_locations(user).exclude(
        latitude__isnull=True, longitude__isnull=True
    )
    nearby = (
        nearby_locations.filter(pk=adventure.location_id).first()
        if adventure.location_id else None
    ) or nearby_locations.order_by("name").first()
    return {
        "recent": (
            {"latitude": float(recent.latitude), "longitude": float(recent.longitude)}
            if recent else None
        ),
        "nearby": (
            {"latitude": float(nearby.latitude), "longitude": float(nearby.longitude)}
            if nearby else None
        ),
        "fallback": {"latitude": 39.5, "longitude": -98.35, "zoom": 4},
    }


def _can_manage_adventure(user, adventure):
    return bool(
        user.is_authenticated
        and user.is_active
        and (
            user.is_staff
            or (
                adventure.owner_id == user.id
                and is_verified_member(user)
            )
        )
    )


def _safe_next_url(request, default):
    next_url = request.POST.get("next", "")
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    if isinstance(default, str) and default.startswith("/"):
        return default
    return reverse(default) if isinstance(default, str) else default


def _photo_taken_at(uploaded_file):
    """Return an aware datetime from EXIF DateTimeOriginal when available."""
    try:
        uploaded_file.seek(0)
        with Image.open(uploaded_file) as image:
            exif = image.getexif()
            raw_date = exif.get(36867) or exif.get(306)

        uploaded_file.seek(0)

        if not raw_date:
            return None

        parsed = datetime.strptime(str(raw_date), "%Y:%m:%d %H:%M:%S")
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    except (OSError, ValueError, TypeError):
        try:
            uploaded_file.seek(0)
        except Exception:
            pass
        return None


def _photo_hash(uploaded_file):
    digest = hashlib.sha256()

    for chunk in uploaded_file.chunks():
        digest.update(chunk)

    uploaded_file.seek(0)
    return digest.hexdigest()


def _save_entry_photos(entry, uploaded_files):
    adventure = entry.adventure
    saved_count = 0
    duplicate_count = 0
    statuses = []

    existing_hashes = set(
        Photo.objects.filter(journal_entry__adventure=adventure)
        .exclude(file_hash="")
        .values_list("file_hash", flat=True)
    )

    for display_order, uploaded_file in enumerate(uploaded_files):
        file_hash = _photo_hash(uploaded_file)

        if file_hash in existing_hashes:
            duplicate_count += 1
            continue

        photo = Photo.objects.create(
            journal_entry=entry,
            image=uploaded_file,
            original_filename=Path(uploaded_file.name).name[:255],
            original_content_type=(getattr(uploaded_file, "content_type", "") or "")[:100],
            taken_at=_photo_taken_at(uploaded_file),
            display_order=display_order,
            file_hash=file_hash,
            moderation_status=Photo.ModerationStatus.PENDING,
        )
        moderate_photo(photo)
        photo.refresh_from_db(fields=["moderation_status"])
        statuses.append(photo.moderation_status)

        existing_hashes.add(file_hash)
        saved_count += 1

    return saved_count, duplicate_count, statuses


def _report_rejected_entry_photos(request, form):
    rejected = getattr(form.fields["photos"], "rejected_files", [])
    if not rejected:
        return
    messages.warning(
        request,
        f"{len(rejected)} photo{'s were' if len(rejected) != 1 else ' was'} rejected.",
    )
    for filename, reason in rejected:
        messages.warning(request, f"{filename}: {reason}")


@verified_member_required
def my_adventures(request):
    adventures = (
        Adventure.objects.filter(owner=request.user)
        .select_related("operating_location", "cover_photo")
        .annotate(
            journal_count=Count("journal_entries", distinct=True),
            photo_count=Count("journal_entries__photos", distinct=True),
            contact_count=Count("journal_entries__contacts", distinct=True) + Count("direct_contacts", filter=Q(direct_contacts__journal_entry__isnull=True), distinct=True),
        )
        .order_by("status", "-updated_at")
    )
    if request.GET.get("source") == "pota":
        adventures = adventures.filter(pota_imports__isnull=False)
    search = request.GET.get("q", "").strip()
    activity = request.GET.get("activity", "").strip()
    place = request.GET.get("place", "").strip()
    if search:
        adventures = adventures.filter(
            Q(title__icontains=search)
            | Q(journal_entries__location__name__icontains=search)
            | Q(journal_entries__location__city__icontains=search)
            | Q(journal_entries__location__state__icontains=search)
        ).distinct()
    if activity == "open":
        adventures = adventures.filter(status=Adventure.Status.ACTIVE)
    elif activity == "complete":
        adventures = adventures.filter(status=Adventure.Status.COMPLETED)
    if place:
        adventures = adventures.filter(
            journal_entries__location_id=place,
            journal_entries__location__in=visible_locations(request.user),
        ).distinct()

    return render(
        request,
        "adventures/my_adventures.html",
        {
            "adventures": adventures,
            "locations": visible_locations(request.user).filter(
                journal_entries__adventure__owner=request.user,
            ).distinct().order_by("name"),
            "search": search,
            "selected_activity": activity,
            "selected_place": place,
        },
    )


def all_adventures(request):
    if request.user.is_staff:
        visible_book_journals = Q()
        visible_book_photos = Q()
    elif request.user.is_authenticated:
        visible_book_journals = Q(owner=request.user) | Q(
            journal_entries__is_public=True
        )
        visible_book_photos = Q(owner=request.user) | Q(
            journal_entries__is_public=True,
            journal_entries__photos__moderation_status=Photo.ModerationStatus.APPROVED,
        )
    else:
        visible_book_journals = Q(journal_entries__is_public=True)
        visible_book_photos = Q(
            journal_entries__is_public=True,
            journal_entries__photos__moderation_status=Photo.ModerationStatus.APPROVED,
        )
    adventures = (
        Adventure.objects.select_related(
            "owner",
            "operating_location",
            "cover_photo",
        )
        .annotate(
            journal_count=Count(
                "journal_entries", filter=visible_book_journals, distinct=True
            ),
            photo_count=Count(
                "journal_entries__photos", filter=visible_book_photos, distinct=True
            ),
            contact_count=Count(
                "journal_entries__contacts",
                filter=visible_book_journals,
                distinct=True,
            ) + Count(
                "direct_contacts",
                filter=Q(direct_contacts__journal_entry__isnull=True),
                distinct=True,
            ),
        )
    )

    # Only public Adventures and the signed-in operator's own private Adventures.
    if request.user.is_authenticated:
        adventures = adventures.filter(Q(is_public=True) | Q(owner=request.user))
    else:
        adventures = adventures.filter(is_public=True)

    if request.user.is_authenticated:
        adventures = adventures.filter(
            Q(is_public=True) | Q(owner=request.user)
        )
    else:
        adventures = adventures.filter(is_public=True)

    search = request.GET.get("q", "").strip()
    state = request.GET.get("state", "").strip()
    place = request.GET.get("place", "").strip()
    sort = request.GET.get("sort", "date")
    activity = request.GET.get("activity", "").strip()

    if search:
        location_search = (
            Q(journal_entries__location__name__icontains=search)
            | Q(journal_entries__location__city__icontains=search)
            | Q(journal_entries__location__state__icontains=search)
        ) & location_access_q(request.user, "journal_entries__location__")
        if request.user.is_authenticated:
            journal_access = Q(owner=request.user) | Q(journal_entries__is_public=True)
        else:
            journal_access = Q(journal_entries__is_public=True)
        adventures = adventures.filter(
            Q(title__icontains=search)
            | Q(owner__username__icontains=search)
            | (location_search & journal_access)
        ).distinct()

    if state:
        if request.user.is_authenticated:
            journal_access = Q(owner=request.user) | Q(journal_entries__is_public=True)
        else:
            journal_access = Q(journal_entries__is_public=True)
        adventures = adventures.filter(
            journal_access,
            location_access_q(request.user, "journal_entries__location__"),
            journal_entries__location__state=state,
        ).distinct()

    if place:
        if request.user.is_authenticated:
            journal_access = Q(owner=request.user) | Q(journal_entries__is_public=True)
        else:
            journal_access = Q(journal_entries__is_public=True)
        adventures = adventures.filter(
            journal_access,
            location_access_q(request.user, "journal_entries__location__"),
            journal_entries__location_id=place,
        ).distinct()

    if activity in {"open", "operating", "progress"}:
        adventures = adventures.filter(status=Adventure.Status.ACTIVE)
    elif activity == "complete":
        adventures = adventures.filter(
            status=Adventure.Status.COMPLETED,
        )

    adventures = adventures.order_by("-started_at", "-updated_at")

    location_journals = Q(journal_entries__adventure__is_public=True, journal_entries__is_public=True)
    if request.user.is_authenticated:
        location_journals |= Q(journal_entries__adventure__owner=request.user)
    book_locations = visible_locations(request.user).filter(location_journals).distinct()
    states = book_locations.exclude(state="").values_list(
        "state", flat=True
    ).distinct().order_by("state")
    locations = book_locations.order_by("name")

    return render(
        request,
        "adventures/all_adventures.html",
        {
            "adventures": adventures,
            "states": states,
            "locations": locations,
            "search": search,
            "selected_state": state,
            "selected_place": place,
            "selected_sort": sort,
            "selected_activity": activity,
        },
    )


def adventure_detail(request, slug):
    adventure = get_object_or_404(
        Adventure.objects.select_related(
            "owner",
            "location",
            "operating_location",
            "cover_photo",
        ).prefetch_related(
            "journal_entries__photos",
            "comments__operator",
        ),
        slug=slug,
    )

    can_manage_adventure = _can_manage_adventure(request.user, adventure)
    if not adventure.is_public and not can_manage_adventure:
        raise Http404("Adventure not found.")

    journal_entries = adventure.journal_entries.all()
    if not can_manage_adventure:
        journal_entries = journal_entries.filter(is_public=True)

    can_view_unapproved_photos = bool(
        request.user.is_staff or request.user == adventure.owner
    )
    visible_photo_filter = Q()
    if not can_view_unapproved_photos:
        visible_photo_filter = Q(photos__moderation_status=Photo.ModerationStatus.APPROVED)
    journal_entries = journal_entries.annotate(
        dashboard_contact_count=Count("contacts", distinct=True),
        dashboard_photo_count=Count(
            "photos", filter=visible_photo_filter, distinct=True
        ),
    ).select_related("location")

    adventure_photos = Photo.objects.filter(
        journal_entry__in=journal_entries,
    ).select_related("journal_entry")
    if adventure.owner != request.user and not request.user.is_staff:
        adventure_photos = adventure_photos.filter(
            moderation_status=Photo.ModerationStatus.APPROVED
        )
    contact_candidates = JournalContact.objects.filter(
        Q(journal_entry__in=journal_entries)
        | Q(adventure=adventure, journal_entry__isnull=True),
    ).distinct().select_related("journal_entry", "resolved_location").order_by(
        "-qso_date", "-time_on", "callsign", "pk"
    )
    contacts = []
    seen_contacts = set()
    for contact in contact_candidates:
        # Imports prevent duplicates inside one Journal. The dashboard also
        # de-duplicates the same QSO when it appears in more than one Journal.
        identity = contact.fingerprint or (
            contact.qso_date,
            contact.time_on,
            contact.callsign.upper(),
            contact.station_callsign.upper(),
            contact.band.upper(),
            contact.mode.upper(),
        )
        if identity in seen_contacts:
            continue
        seen_contacts.add(identity)
        contacts.append(contact)
    contact_count = len(contacts)
    pota_rollup = aggregate_pota_journals(journal_entries)
    contact_map = build_contact_map(adventure, contacts, request.user)
    can_manage_journals = can_manage_adventure
    photo_upload_entry = journal_entries.first() if can_manage_journals else None
    if photo_upload_entry is not None:
        photo_add_url = (
            reverse("edit_journal_entry", args=[photo_upload_entry.pk])
            + "#journal-photo-upload"
        )
    elif can_manage_journals:
        photo_add_url = (
            reverse("add_journal_entry", args=[adventure.slug])
            + "#journal-photo-upload"
        )
    else:
        photo_add_url = ""
    can_view_adventure_location = can_view_location(request.user, adventure.location)
    visible_location = adventure.location if can_view_adventure_location else None
    journal_entry_rows = list(journal_entries)
    for item in journal_entry_rows:
        item.can_view_location = can_view_location(request.user, item.location)
    display_cover_photo = adventure.display_cover_photo
    adventure_reference = (adventure.operating_callsign_url or "").strip()
    if (
        can_manage_adventure
        and adventure.cover_photo_is_explicit
        and (
            not adventure.cover_photo_id
            or not display_cover_photo
            or display_cover_photo.pk != adventure.cover_photo_id
        )
    ):
        messages.warning(
            request,
            "Your selected Adventure cover is no longer publicly available. "
            "Another approved photo or the generic Adventure image is now being used.",
        )

    return render(
        request,
        "adventures/adventure_detail.html",
        {
            "adventure": adventure,
            "adventure_reference": adventure_reference,
            "adventure_reference_url": _safe_external_reference_url(adventure_reference),
            "journal_entries": journal_entry_rows,
            "adventure_photos": adventure_photos,
            "contacts": contacts,
            "contact_count": contact_count,
            "pota_rollup": pota_rollup,
            "contact_map": contact_map,
            "contact_map_dom_id": "adventure-contact-map",
            "contact_map_data_id": "adventure-contact-map-data",
            "can_manage_adventure": can_manage_adventure,
            "can_manage_journals": can_manage_journals,
            "can_view_unapproved_photos": can_view_unapproved_photos,
            "journal_entry_count": len(journal_entry_rows),
            "photo_add_url": photo_add_url,
            "can_view_adventure_location": can_view_adventure_location,
            "can_edit_adventure_location_pin": bool(
                visible_location
                and can_edit_location_pin(request.user, visible_location)
            ),
            "single_location_map_data": (
                {
                    "name": visible_location.name,
                    "latitude": float(visible_location.latitude),
                    "longitude": float(visible_location.longitude),
                }
                if visible_location
                and visible_location.latitude is not None
                and visible_location.longitude is not None
                else None
            ),
            "display_cover_photo": display_cover_photo,
            "journal_location_map_data": [
                {"name": item.location.name, "journal": item.title or "Journal Entry",
                 "url": reverse("journal_entry_detail", args=[item.pk]),
                 "latitude": float(item.latitude), "longitude": float(item.longitude),
                 "status": item.status}
                for item in journal_entry_rows
                if item.location and item.latitude is not None and item.longitude is not None
                and can_view_location(request.user, item.location)
            ],
        },
    )


def adventure_contacts(request, slug):
    adventure = get_object_or_404(
        Adventure.objects.select_related("owner"),
        slug=slug,
    )
    can_manage_adventure = _can_manage_adventure(request.user, adventure)
    if not adventure.is_public and not can_manage_adventure:
        raise Http404("Adventure not found.")

    journal_entries = adventure.journal_entries.order_by("-entry_at", "-pk")
    if not can_manage_adventure:
        journal_entries = journal_entries.filter(is_public=True)

    authorized_contacts = list(JournalContact.objects.filter(
        Q(journal_entry__in=journal_entries)
        | Q(adventure=adventure, journal_entry__isnull=True),
    ).distinct().select_related("journal_entry").order_by(
        "-qso_date", "-time_on", "callsign"
    ))
    search_query = request.GET.get("q", "").strip()[:100]
    selected_band = request.GET.get("band", "").strip()[:24]
    selected_mode = request.GET.get("mode", "").strip()[:32]

    def matches_table_filters(contact):
        if selected_band and contact.band != selected_band:
            return False
        if selected_mode and contact.mode != selected_mode:
            return False
        if search_query:
            searchable = " ".join((
                contact.callsign,
                contact.name,
                contact.state,
                contact.country,
                contact.pota_park_reference,
                contact.pota_park_name,
            )).casefold()
            if search_query.casefold() not in searchable:
                return False
        return True

    contacts = [contact for contact in authorized_contacts if matches_table_filters(contact)]
    return render(
        request,
        "adventures/adventure_contacts.html",
        {
            "adventure": adventure,
            "journal_entries": journal_entries,
            "contacts": contacts,
            "contact_count": len(authorized_contacts),
            "filtered_contact_count": len(contacts),
            "contact_band_options": sorted(
                {contact.band for contact in authorized_contacts if contact.band},
                key=str.casefold,
            ),
            "contact_mode_options": sorted(
                {contact.mode for contact in authorized_contacts if contact.mode},
                key=str.casefold,
            ),
            "contact_search_query": search_query,
            "selected_contact_band": selected_band,
            "selected_contact_mode": selected_mode,
            "can_manage_adventure": can_manage_adventure,
        },
    )


def adventure_journals(request, slug):
    adventure = get_object_or_404(Adventure.objects.select_related("owner"), slug=slug)
    can_manage_adventure = _can_manage_adventure(request.user, adventure)
    if not adventure.is_public and not can_manage_adventure:
        raise Http404("Adventure not found.")
    journals = adventure.journal_entries.all()
    if not can_manage_adventure:
        journals = journals.filter(is_public=True)
    journal_count_totals = aggregate_pota_journals(journals)
    visible_photo_filter = Q()
    if not can_manage_adventure:
        visible_photo_filter = Q(
            photos__moderation_status=Photo.ModerationStatus.APPROVED
        )
    journals = journals.annotate(
        dashboard_contact_count=Count("contacts", distinct=True),
        dashboard_photo_count=Count(
            "photos", filter=visible_photo_filter, distinct=True
        ),
    ).select_related("location", "pota_import").order_by("-entry_at", "-pk")
    journal_rows = list(journals)
    for item in journal_rows:
        item.can_view_location = can_view_location(request.user, item.location)
    return render(request, "adventures/adventure_journals.html", {
        "adventure": adventure,
        "journal_entries": journal_rows,
        "journal_count_totals": journal_count_totals,
        "can_manage_adventure": can_manage_adventure,
        "eligible_journal_count": len(journal_rows) if can_manage_adventure else 0,
    })


def _bulk_deletable_journals(user, adventure):
    if not _can_manage_adventure(user, adventure):
        return JournalEntry.objects.none()
    return JournalEntry.objects.filter(adventure=adventure)


def _validated_bulk_journal_ids(user, adventure, submitted_ids):
    if not isinstance(submitted_ids, list) or not submitted_ids:
        return None, "Select at least one Journal."
    normalized_ids = []
    for value in submitted_ids:
        try:
            normalized_id = int(value)
        except (TypeError, ValueError, OverflowError):
            return None, "The selected Journal list is invalid."
        if (
            isinstance(value, bool)
            or normalized_id < 1
            or str(value).strip() != str(normalized_id)
        ):
            return None, "The selected Journal list is invalid."
        normalized_ids.append(normalized_id)
    if len(normalized_ids) != len(set(normalized_ids)):
        return None, "The selected Journal list contains duplicate IDs."
    eligible_ids = set(
        _bulk_deletable_journals(user, adventure)
        .filter(pk__in=normalized_ids)
        .values_list("pk", flat=True)
    )
    if eligible_ids != set(normalized_ids):
        return None, "One or more selected Journals do not belong to this Adventure or are not authorized."
    return normalized_ids, None


@verified_member_or_staff_required
@require_GET
def select_adventure_journals(request, slug):
    adventure = get_object_or_404(Adventure.objects.select_related("owner"), slug=slug)
    if not _can_manage_adventure(request.user, adventure):
        return HttpResponseForbidden(
            "Only the Adventure owner or authorized staff can select Journals."
        )
    eligible_ids = list(
        _bulk_deletable_journals(request.user, adventure)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    mode = request.GET.get("mode", "")
    if mode == "all":
        selected_ids = eligible_ids
    elif mode == "none":
        selected_ids = []
    elif mode == "random":
        raw_count = request.GET.get("count", "")
        try:
            count = int(raw_count)
        except (TypeError, ValueError, OverflowError):
            count = 0
        if count < 1 or raw_count.strip() != str(count):
            return JsonResponse(
                {"error": "Enter a whole number of Journals from 1 through the eligible count.", "eligible_count": len(eligible_ids)},
                status=400,
            )
        if count > len(eligible_ids):
            return JsonResponse(
                {"error": f"Only {len(eligible_ids)} Journals are eligible in this Adventure.", "eligible_count": len(eligible_ids)},
                status=400,
            )
        selected_ids = random.sample(eligible_ids, count)
    else:
        return JsonResponse({"error": "Choose a valid Journal selection option."}, status=400)
    response = JsonResponse(
        {"journal_ids": selected_ids, "selected_count": len(selected_ids), "eligible_count": len(eligible_ids)}
    )
    response["Cache-Control"] = "no-store"
    return response


def _posted_bulk_journal_ids(request):
    try:
        submitted_ids = json.loads(request.POST.get("selected_journal_ids", ""))
    except (TypeError, ValueError):
        return None, "The selected Journal list is invalid."
    return submitted_ids, None


@verified_member_or_staff_required
@require_POST
def bulk_delete_adventure_journals(request, slug):
    adventure = get_object_or_404(Adventure.objects.select_related("owner"), slug=slug)
    if not _can_manage_adventure(request.user, adventure):
        return HttpResponseForbidden(
            "Only the Adventure owner or authorized staff can delete Journals."
        )
    decision = request.POST.get("decision", "review")
    if decision == "review":
        submitted_ids, parse_error = _posted_bulk_journal_ids(request)
        if parse_error:
            return HttpResponseBadRequest(parse_error)
        journal_ids, validation_error = _validated_bulk_journal_ids(
            request.user, adventure, submitted_ids
        )
        if validation_error:
            return HttpResponseBadRequest(validation_error)
        confirmation_token = uuid4().hex
        request.session[PENDING_JOURNAL_BULK_DELETE_SESSION_KEY] = {
            "token": confirmation_token,
            "user_id": request.user.pk,
            "adventure_id": adventure.pk,
            "journal_ids": journal_ids,
        }
        return render(request, "adventures/confirm_bulk_journal_delete.html", {
            "adventure": adventure,
            "journal_count": len(journal_ids),
            "confirmation_token": confirmation_token,
        })
    if decision not in {"confirm", "cancel"}:
        return HttpResponseBadRequest("Choose Confirm Delete or Cancel.")
    pending = request.session.get(PENDING_JOURNAL_BULK_DELETE_SESSION_KEY)
    token = request.POST.get("confirmation_token", "")
    if (
        not pending
        or not token
        or pending.get("token") != token
        or pending.get("user_id") != request.user.pk
        or pending.get("adventure_id") != adventure.pk
    ):
        return HttpResponseBadRequest("That Journal deletion confirmation is missing or expired.")
    if decision == "cancel":
        request.session.pop(PENDING_JOURNAL_BULK_DELETE_SESSION_KEY, None)
        messages.info(request, "Journal deletion canceled. No Journals were deleted.")
        return redirect("adventure_journals", slug=adventure.slug)
    journal_ids, validation_error = _validated_bulk_journal_ids(
        request.user, adventure, pending.get("journal_ids")
    )
    if validation_error:
        return HttpResponseBadRequest(validation_error)
    with transaction.atomic():
        locked_adventure = Adventure.objects.select_for_update().get(pk=adventure.pk)
        if not _can_manage_adventure(request.user, locked_adventure):
            return HttpResponseForbidden(
                "Only the Adventure owner or authorized staff can delete Journals."
            )
        selected_journals = JournalEntry.objects.select_for_update().filter(
            adventure=locked_adventure,
            pk__in=journal_ids,
        )
        if set(selected_journals.values_list("pk", flat=True)) != set(journal_ids):
            return HttpResponseBadRequest(
                "The selected Journals changed before confirmation. Nothing was deleted."
            )
        deleting_cover = bool(
            locked_adventure.cover_photo_id
            and selected_journals.filter(
                photos__pk=locked_adventure.cover_photo_id
            ).exists()
        )
        deleted_count = selected_journals.count()
        selected_journals.delete()
        if deleting_cover:
            Adventure.objects.filter(pk=locked_adventure.pk).update(
                cover_photo=None,
                cover_photo_is_explicit=False,
                updated_at=timezone.now(),
            )
        locked_adventure.refresh_status_from_journals()
    request.session.pop(PENDING_JOURNAL_BULK_DELETE_SESSION_KEY, None)
    messages.success(
        request,
        f"Deleted {deleted_count} Journals from {adventure.title} (Adventure ID {adventure.pk}).",
    )
    return redirect("adventure_journals", slug=adventure.slug)


@verified_member_or_staff_required
def adventure_import_contacts(request, slug):
    adventure = get_object_or_404(Adventure, slug=slug)
    if not _can_manage_adventure(request.user, adventure):
        return HttpResponseForbidden(
            "Only the Adventure owner or authorized staff can import contacts."
        )
    journal_entries = adventure.journal_entries.annotate(
        aggregated_contact_count=Count("contacts")
    ).order_by("-entry_at", "-pk")
    if request.method == "POST":
        entry = get_object_or_404(
            journal_entries,
            pk=request.POST.get("journal_entry"),
        )
        return redirect(
            reverse("import_adif", args=[entry.pk])
            + "?return_to="
            + reverse("adventure_contacts", args=[adventure.slug])
        )
    return render(
        request,
        "adventures/adventure_import_contacts.html",
        {
            "adventure": adventure,
            "journal_entries": journal_entries,
            "journal_count": journal_entries.count(),
        },
    )


@verified_member_required
@require_POST
def start_adventure_here(request, location_id):
    location = get_object_or_404(visible_locations(request.user), pk=location_id)

    adventure = Adventure.objects.create(
        owner=request.user,
        location=location,
        status=Adventure.Status.ACTIVE,
    )

    return redirect("edit_adventure", slug=adventure.slug)


@verified_member_required
def add_adventure(request):
    draft_title = request.GET.get("title", "")
    draft_public = request.GET.get("public", "1")

    if request.method == "POST":
        form_data = request.POST.copy()
        profile = getattr(request.user, "member_profile", None)
        form_data.setdefault(
            "operating_callsign",
            profile.callsign if profile and profile.callsign else request.user.username,
        )
        form_data.setdefault(
            "operating_callsign_type", Adventure.OperatingCallsignType.PERSONAL
        )
        if (
            "adventure_visibility_present" not in form_data
            and "is_public" not in form_data
        ):
            form_data["is_public"] = "on"
        form = AdventureForm(form_data, user=request.user)

        if form.is_valid():
            try:
                with transaction.atomic():
                    adventure = form.save(commit=False)
                    adventure.owner = request.user
                    adventure.status = Adventure.Status.ACTIVE
                    adventure.save()
            except Exception as exc:
                logger.exception(
                    "Adventure create transaction failed user_id=%s exception=%s",
                    request.user.pk,
                    type(exc).__name__,
                )
                form.add_error(
                    None,
                    "The Adventure could not be saved. Correct the errors and try again.",
                )
            else:
                messages.success(request, "Adventure saved successfully.")
                return redirect("my_adventures")
    else:
        initial = {
            "title": draft_title,
            "is_public": draft_public != "0",
        }

        form = AdventureForm(initial=initial, user=request.user)
    return render(
        request,
        "adventures/adventure_form.html",
        {
            "form": form,
            "page_title": "Add New Adventure",
            "adventure": None,
        },
    )


@verified_member_required
@require_POST
def create_operating_position_inline(request, location_id):
    location = get_object_or_404(visible_locations(request.user), pk=location_id)
    form = OperatingLocationForm(
        {
            "name": request.POST.get("name", ""),
            "description": request.POST.get("description", ""),
            "latitude": request.POST.get("latitude", ""),
            "longitude": request.POST.get("longitude", ""),
        }
    )

    if not form.is_valid():
        return JsonResponse(form_error_payload(form), status=400)

    if (
        form.cleaned_data["latitude"] is None
        or form.cleaned_data["longitude"] is None
    ):
        return JsonResponse(
            validation_error_payload(
                {"coordinates": [{"message": "Choose a point on the map.", "code": "required"}]},
                required_missing=True,
            ),
            status=400,
        )

    position = form.save(commit=False)
    position.location = location
    position.created_by = request.user
    position.save()

    return JsonResponse(
        {
            "id": position.pk,
            "location_id": location.pk,
            "name": position.name,
            "description": position.description,
            "latitude": float(position.latitude),
            "longitude": float(position.longitude),
        },
        status=201,
    )


@verified_member_or_staff_required
def edit_adventure(request, slug):
    adventure = get_object_or_404(Adventure, slug=slug)

    if not _can_manage_adventure(request.user, adventure):
        return HttpResponseForbidden(
            "Only the Adventure owner or an authorized administrator can edit it."
        )

    if request.method == "POST":
        form_data = request.POST.copy()
        form_data.setdefault("operating_callsign", adventure.operating_callsign)
        form_data.setdefault(
            "operating_callsign_type", adventure.operating_callsign_type
        )
        form = AdventureForm(form_data, instance=adventure, user=request.user)

        if form.is_valid():
            try:
                with transaction.atomic():
                    adventure = form.save()
            except Exception as exc:
                logger.exception(
                    "Adventure edit transaction failed adventure_id=%s user_id=%s "
                    "exception=%s",
                    adventure.pk,
                    request.user.pk,
                    type(exc).__name__,
                )
                form.add_error(
                    None,
                    "The Adventure could not be saved. Correct the errors and try again.",
                )
            else:
                messages.success(request, "Adventure saved successfully.")
                return redirect("my_adventures")
    else:
        form = AdventureForm(instance=adventure, user=request.user)

    journal_entries = adventure.journal_entries.prefetch_related("photos").all()

    return render(
        request,
        "adventures/adventure_form.html",
        {
            "form": form,
            "page_title": "Edit Adventure",
            "adventure": adventure,
            "journal_entries": journal_entries,
        },
    )



@verified_member_or_staff_required
@require_POST
def toggle_adventure_visibility(request, slug):
    adventure = get_object_or_404(Adventure, slug=slug)
    if not _can_manage_adventure(request.user, adventure):
        return HttpResponseForbidden(
            "Only the Adventure owner or authorized staff can change its visibility."
        )
    adventure.is_public = not adventure.is_public
    adventure.save(update_fields=["is_public", "updated_at"])
    return redirect(request.POST.get("next") or adventure.get_absolute_url())


@verified_member_or_staff_required
@require_POST
def delete_adventure(request, slug):
    adventure = get_object_or_404(Adventure, slug=slug)
    if not _can_manage_adventure(request.user, adventure):
        return HttpResponseForbidden(
            "Only the Adventure owner or an authorized administrator can delete it."
        )
    owner_id = adventure.owner_id
    adventure.delete()
    messages.success(request, "Adventure deleted.")
    default = "my_adventures" if owner_id == request.user.id else "all_adventures"
    return redirect(_safe_next_url(request, default))


@verified_member_or_staff_required
@require_POST
def toggle_journal_visibility(request, entry_id):
    entry = get_object_or_404(
        JournalEntry.objects.select_related("adventure"),
        pk=entry_id,
    )

    if not _can_manage_adventure(request.user, entry.adventure):
        return HttpResponseForbidden(
            "Only the Adventure owner or authorized staff can change Journal visibility."
        )

    entry.is_public = not entry.is_public
    entry.save(update_fields=["is_public", "updated_at"])
    entry.adventure.save(update_fields=["updated_at"])
    messages.success(
        request,
        f"Journal visibility changed to {'Public' if entry.is_public else 'Private'}.",
    )
    return redirect("journal_entry_detail", entry_id=entry.pk)


@verified_member_or_staff_required
@require_POST
def delete_selected_contacts(request, entry_id):
    entry = get_object_or_404(
        JournalEntry.objects.select_related("adventure"),
        pk=entry_id,
    )

    if not _can_manage_adventure(request.user, entry.adventure):
        return HttpResponseForbidden(
            "Only the Adventure owner or authorized staff can delete contacts."
        )

    selected_ids = request.POST.getlist("contact_ids")

    if not selected_ids:
        messages.info(request, "No contacts were selected.")
        return redirect("journal_entry_detail", entry_id=entry.pk)

    contacts = entry.contacts.filter(pk__in=selected_ids)
    deleted_count = contacts.count()
    contacts.delete()

    entry.adventure.save(update_fields=["updated_at"])

    messages.success(
        request,
        f"{deleted_count} contact"
        f"{'s' if deleted_count != 1 else ''} deleted.",
    )

    return redirect("journal_entry_detail", entry_id=entry.pk)


@verified_member_or_staff_required
@require_POST
def delete_journal_contact(request, entry_id, contact_id):
    entry = get_object_or_404(JournalEntry.objects.select_related("adventure"), pk=entry_id)
    if not _can_manage_adventure(request.user, entry.adventure):
        return HttpResponseForbidden(
            "Only the Adventure owner or authorized staff can delete contacts."
        )
    contact = get_object_or_404(entry.contacts, pk=contact_id)
    contact.delete()
    entry.adventure.save(update_fields=["updated_at"])
    messages.success(request, "Contact deleted.")
    return redirect("journal_entry_detail", entry_id=entry.pk)


@verified_member_or_staff_required
@require_POST
def mark_adventure_done(request, slug):
    adventure = get_object_or_404(Adventure, slug=slug)
    if not _can_manage_adventure(request.user, adventure):
        return HttpResponseForbidden(
            "Only the Adventure owner or an authorized administrator can change its status."
        )
    adventure.status = Adventure.Status.COMPLETED
    adventure.save()
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse(
            {
                "status": adventure.status,
                "label": adventure.display_status_label,
                "key": adventure.display_status_key,
                "toggle_url": reverse(
                    "mark_adventure_in_progress",
                    kwargs={"slug": adventure.slug},
                ),
            }
        )
    return redirect(_safe_next_url(request, "my_adventures"))


@verified_member_or_staff_required
@require_POST
def mark_adventure_in_progress(request, slug):
    adventure = get_object_or_404(Adventure, slug=slug)
    if not _can_manage_adventure(request.user, adventure):
        return HttpResponseForbidden(
            "Only the Adventure owner or an authorized administrator can change its status."
        )
    adventure.status = Adventure.Status.ACTIVE
    adventure.save()
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse(
            {
                "status": adventure.status,
                "label": adventure.display_status_label,
                "key": adventure.display_status_key,
                "toggle_url": reverse(
                    "mark_adventure_done",
                    kwargs={"slug": adventure.slug},
                ),
            }
        )
    return redirect(_safe_next_url(request, "my_adventures"))


@verified_member_or_staff_required
def add_journal_entry(request, slug):
    adventure = get_object_or_404(Adventure, slug=slug)

    if not _can_manage_adventure(request.user, adventure):
        return HttpResponseForbidden(
            "Only the Adventure owner or authorized staff can add Journal entries."
        )

    if request.method == "POST":
        submitted_photos = request.FILES.getlist("photos")
        form_data = request.POST.copy()
        form_data.setdefault("operating_callsign", adventure.operating_callsign)
        form_data.setdefault("status", JournalEntry.Status.OPEN)
        if not form_data.get("location_name") and form_data.get("location"):
            posted_location = visible_locations(request.user).filter(pk=form_data["location"]).first()
            if posted_location:
                form_data["location_name"] = posted_location.name
        if not form_data.get("location_name") and not form_data.get("location") and adventure.location_id:
            form_data["location"] = str(adventure.location_id)
            form_data["location_name"] = adventure.location.name
            latitude = adventure.location.latitude
            longitude = adventure.location.longitude
            if (latitude is None or longitude is None) and adventure.operating_location_id:
                latitude = adventure.operating_location.latitude
                longitude = adventure.operating_location.longitude
            if latitude is not None and longitude is not None:
                form_data.setdefault("latitude", str(latitude))
                form_data.setdefault("longitude", str(longitude))
        if (
            "journal_visibility_present" not in form_data
            and "is_public" not in form_data
        ):
            form_data["is_public"] = "on"
        form = JournalEntryForm(form_data, request.FILES, adventure=adventure, user=request.user)

        if form.is_valid():
            with transaction.atomic():
                location = form.resolve_location(request.user)
                entry = form.save(commit=False)
                entry.adventure = adventure
                entry.location = location
                entry.save()

                saved_count, duplicate_count, statuses = _save_entry_photos(
                    entry,
                    [
                        photo for photo in submitted_photos
                        if photo in (form.cleaned_data.get("photos") or [])
                    ],
                )
                adventure.save(update_fields=["updated_at"])


            if saved_count:
                messages.success(
                    request,
                    f"{saved_count} photo{'s' if saved_count != 1 else ''} added to the Journal Entry.",
                )
                add_photo_upload_notice(request, statuses)
            if duplicate_count:
                messages.info(
                    request,
                    f"{duplicate_count} duplicate photo{'s were' if duplicate_count != 1 else ' was'} skipped.",
                )
            _report_rejected_entry_photos(request, form)


            if request.POST.get("return_to_contacts") == "1":
                messages.success(
                    request,
                    f"Journal Entry created: {entry.title or 'Journal Entry'}.",
                )
                return redirect("adventure_import_contacts", slug=adventure.slug)
            return redirect("journal_entry_detail", entry_id=entry.pk)
    else:
        last_entry = adventure.journal_entries.filter(
            is_adventure_photo_collection=False
        ).order_by("-entry_at", "-pk").first()
        previous_location_entries = adventure.journal_entries.select_related("location").filter(
            is_adventure_photo_collection=False,
            location__isnull=False,
            latitude__isnull=False,
            longitude__isnull=False,
        ).order_by("-entry_at", "-pk")
        previous_location_entry = next(
            (
                entry
                for entry in previous_location_entries
                if can_view_location(request.user, entry.location)
            ),
            None,
        )
        initial = {"operating_callsign": adventure.operating_callsign}

        if last_entry:
            initial = {
                "operating_callsign": adventure.operating_callsign,
                "portable": last_entry.portable,
                "mobile": last_entry.mobile,
                "pota": last_entry.pota,
                "sota": last_entry.sota,
                "qrp": last_entry.qrp,
                "wwff": last_entry.wwff,
                "contest": last_entry.contest,
                "field_day": last_entry.field_day,
                "club_event": last_entry.club_event,
                "mode_ssb": last_entry.mode_ssb,
                "mode_cw": last_entry.mode_cw,
                "mode_digital": last_entry.mode_digital,
                "mode_fm": last_entry.mode_fm,
                "mode_am": last_entry.mode_am,
                "mode_other": last_entry.mode_other,
            }
        if previous_location_entry:
            initial.update({
                "location": previous_location_entry.location_id,
                "location_name": previous_location_entry.location.name,
                "latitude": previous_location_entry.latitude,
                "longitude": previous_location_entry.longitude,
                "location_source": "existing",
            })

        form = JournalEntryForm(initial=initial, adventure=adventure, user=request.user)

    return render(
        request,
        "adventures/add_journal_entry.html",
        {
            "adventure": adventure,
            "form": form,
            "journal_location_choices": _journal_location_choices(request.user),
            "journal_map_defaults": _journal_map_defaults(adventure, request.user),
            "return_to_contacts": (
                request.GET.get("return_to") == "contacts"
                or request.POST.get("return_to_contacts") == "1"
            ),
        },
    )




def journal_entry_detail(request, entry_id):
    entry = get_object_or_404(
        JournalEntry.objects.select_related(
            "adventure",
            "adventure__owner",
            "adventure__location",
            "location",
        ).prefetch_related("photos", "contacts__resolved_location"),
        pk=entry_id,
    )

    if not request.user.is_staff and entry.adventure.owner != request.user and (
        not entry.adventure.is_public or not entry.is_public
    ):
        raise Http404("Journal Entry not found.")

    contacts = entry.contacts.select_related("journal_entry", "resolved_location").order_by("-qso_date", "-time_on", "callsign")
    can_edit_journal = _can_manage_adventure(request.user, entry.adventure)
    can_review_photos = bool(request.user.is_staff)
    journal_photos_query = entry.photos.all()
    if not (can_edit_journal or can_review_photos):
        journal_photos_query = journal_photos_query.filter(
            moderation_status=Photo.ModerationStatus.APPROVED
        )
    journal_photos = list(journal_photos_query)
    primary_journal_photo = next(
        (photo for photo in journal_photos if photo.pk == entry.primary_photo_id),
        next(
            (photo for photo in journal_photos if photo.is_publicly_visible),
            journal_photos[0] if journal_photos else None,
        ),
    )
    longest_contact = (
        contacts.exclude(distance_miles__isnull=True)
        .order_by("-distance_miles")
        .first()
    )
    country_count = (
        contacts.exclude(country="")
        .values("country")
        .distinct()
        .count()
    )
    state_count = (
        contacts.exclude(state="")
        .values("state", "country")
        .distinct()
        .count()
    )

    return render(
        request,
        "adventures/journal_entry_detail.html",
        {
            "adventure": entry.adventure,
            "entry": entry,
            "contacts": contacts,
            "contact_count": contacts.count(),
            "longest_contact": longest_contact,
            "country_count": country_count,
            "state_count": state_count,
            "can_edit_journal": can_edit_journal,
            "can_review_photos": can_review_photos,
            "journal_photos": journal_photos,
            "journal_photo_count": len(journal_photos),
            "primary_journal_photo": primary_journal_photo,
            "can_manage_adventure": _can_manage_adventure(request.user, entry.adventure),
            "can_view_adventure": bool(
                entry.adventure.is_public or entry.adventure.owner == request.user
            ),
            "can_manage_contacts": can_edit_journal,
            "has_imported_pota_history": bool(
                can_edit_journal
                and eligible_pota_journal_imports().filter(
                    journal_entry_id=entry.pk
                ).exists()
            ),
            "can_view_journal_location": can_view_location(request.user, entry.location),
            "single_location_map_data": (
                {"name": entry.location.name, "latitude": float(entry.latitude), "longitude": float(entry.longitude)}
                if entry.location and entry.latitude is not None and entry.longitude is not None
                and can_view_location(request.user, entry.location) else None
            ),
            "can_edit_journal_pin": can_edit_journal,
        },
    )


def journal_contact_map(request, entry_id):
    entry = get_object_or_404(
        JournalEntry.objects.select_related(
            "adventure", "adventure__owner", "location"
        ),
        pk=entry_id,
    )
    if not request.user.is_staff and entry.adventure.owner != request.user and (
        not entry.adventure.is_public or not entry.is_public
    ):
        raise Http404("Journal Entry not found.")

    return redirect(
        f'{reverse("adventure_contact_geography", args=[entry.adventure.slug])}?journal={entry.pk}'
    )


def adventure_contact_geography(request, slug):
    adventure = get_object_or_404(Adventure.objects.select_related("owner", "location"), slug=slug)
    can_manage = _can_manage_adventure(request.user, adventure)
    if not adventure.is_public and not can_manage:
        raise Http404("Adventure not found.")
    journals = adventure.journal_entries.select_related("location").order_by("-entry_at", "-pk")
    if not can_manage and not request.user.is_staff:
        journals = journals.filter(is_public=True)
    journals = list(journals)
    contacts = list(JournalContact.objects.filter(
        Q(journal_entry__in=journals) | Q(adventure=adventure, journal_entry__isnull=True)
    ).distinct().select_related("journal_entry", "resolved_location").order_by("journal_entry_id", "pk"))
    contact_map = build_adventure_contact_map(adventure, journals, contacts, request.user)
    selected_journal_id = request.GET.get("journal", "")
    if selected_journal_id not in {str(journal.pk) for journal in journals}:
        selected_journal_id = ""
    return render(
        request,
        "adventures/journal_contact_map.html",
        {
            "adventure": adventure,
            "entry": None,
            "contact_map": contact_map,
            "contact_map_dom_id": f"adventure-{adventure.pk}-contact-map",
            "contact_map_data_id": f"adventure-{adventure.pk}-contact-map-data",
            "contact_map_heading": f"Contacts from Adventure - {adventure.title}",
            "contact_map_origin_label": "Journal Location",
            "selected_journal_id": selected_journal_id,
        },
    )


@verified_member_or_staff_required
@require_POST
def toggle_journal_status(request, entry_id):
    with transaction.atomic():
        entry = get_object_or_404(
            JournalEntry.objects.select_for_update().select_related(
                "adventure", "adventure__owner"
            ),
            pk=entry_id,
        )
        if not _can_manage_adventure(request.user, entry.adventure):
            return HttpResponseForbidden(
                "Only the Journal owner or authorized staff can change its status."
            )
        entry.status = (
            JournalEntry.Status.COMPLETED
            if entry.status == JournalEntry.Status.OPEN
            else JournalEntry.Status.OPEN
        )
        entry.save(update_fields=["status", "updated_at"])

    messages.success(request, f"Journal status changed to {entry.display_status_label}.")
    return redirect(
        _safe_next_url(
            request,
            reverse("journal_entry_detail", kwargs={"entry_id": entry.pk}),
        )
    )


def journal_photo_gallery(request, entry_id):
    entry = get_object_or_404(
        JournalEntry.objects.select_related("adventure", "adventure__owner"),
        pk=entry_id,
    )
    can_manage_adventure = _can_manage_adventure(request.user, entry.adventure)
    if not can_manage_adventure and (
        not entry.adventure.is_public or not entry.is_public
    ):
        raise Http404("Journal Entry not found.")

    can_edit_journal = can_manage_adventure
    can_delete_photos = can_manage_adventure
    can_review_photos = bool(request.user.is_staff)
    photos_query = entry.photos.all()
    if not (can_edit_journal or can_review_photos):
        photos_query = photos_query.filter(
            moderation_status=Photo.ModerationStatus.APPROVED
        )
    return render(
        request,
        "adventures/journal_photo_gallery.html",
        {
            "adventure": entry.adventure,
            "entry": entry,
            "journal_photos": list(photos_query),
            "can_edit_journal": can_edit_journal,
            "can_delete_photos": can_delete_photos,
            "can_review_photos": can_review_photos,
            "can_manage_adventure": can_manage_adventure,
        },
    )


def _delete_photo_records(photos):
    photos = list(photos)
    if not photos:
        return 0
    names = {
        image.name
        for photo in photos
        for image in (
            photo.image,
            photo.moderation_image,
            photo.web_image,
            photo.thumbnail_image,
        )
        if image and image.name
    }
    storage = photos[0].image.storage
    photo_ids = [photo.pk for photo in photos]
    cover_adventure_ids = list(
        Adventure.objects.filter(cover_photo_id__in=photo_ids).values_list("pk", flat=True)
    )
    Photo.objects.filter(pk__in=photo_ids).delete()
    if cover_adventure_ids:
        Adventure.objects.filter(pk__in=cover_adventure_ids).update(
            cover_photo_is_explicit=False,
            updated_at=timezone.now(),
        )

    def remove_unshared_files():
        for name in names:
            still_referenced = Photo.objects.filter(
                Q(image=name)
                | Q(moderation_image=name)
                | Q(web_image=name)
                | Q(thumbnail_image=name)
            ).exists()
            if not still_referenced and storage.exists(name):
                storage.delete(name)

    transaction.on_commit(remove_unshared_files)
    return len(photo_ids)


@verified_member_or_staff_required
@require_POST
def delete_journal_photos(request, entry_id):
    entry = get_object_or_404(
        JournalEntry.objects.select_related("adventure", "adventure__owner"),
        pk=entry_id,
    )
    if not _can_manage_adventure(request.user, entry.adventure):
        return HttpResponseForbidden(
            "Only the Journal owner or authorized staff can delete its photos."
        )

    mode = request.POST.get("delete_mode")
    journal_photos = entry.photos.all()
    if mode == "all":
        photos = list(journal_photos)
        action_label = "all"
    elif mode in {"selected", "individual"}:
        raw_ids = request.POST.getlist("photo_ids")
        if not raw_ids or any(not value.isdigit() for value in raw_ids):
            return HttpResponseBadRequest("Select valid photos to delete.")
        requested_ids = {int(value) for value in raw_ids}
        photos = list(journal_photos.filter(pk__in=requested_ids))
        if {photo.pk for photo in photos} != requested_ids:
            return HttpResponseBadRequest(
                "Every selected photo must belong to this Journal. Nothing was deleted."
            )
        if mode == "individual" and len(photos) != 1:
            return HttpResponseBadRequest("Choose exactly one photo to delete.")
        action_label = "selected"
    else:
        return HttpResponseBadRequest("Choose a valid photo deletion action.")

    with transaction.atomic():
        deleted = _delete_photo_records(photos)
        entry.adventure.save(update_fields=["updated_at"])
    if deleted:
        messages.success(
            request,
            f"Deleted {deleted} {action_label} photo{'s' if deleted != 1 else ''} from this Journal.",
        )
    else:
        messages.info(request, "No photos were deleted.")
    return redirect("journal_photo_gallery", entry_id=entry.pk)


@verified_member_or_staff_required
@require_POST
def make_journal_photo(request, entry_id, photo_id):
    entry = get_object_or_404(
        JournalEntry.objects.select_related("adventure"), pk=entry_id
    )
    if not _can_manage_adventure(request.user, entry.adventure):
        return HttpResponseForbidden(
            "Only the Journal owner or authorized staff can change its primary photo."
        )
    photo = get_object_or_404(Photo, pk=photo_id, journal_entry=entry)
    if not photo.is_publicly_visible:
        return HttpResponseForbidden(
            "Only an approved photo can be used as the Journal photo."
        )
    entry.primary_photo = photo
    entry.save(update_fields=["primary_photo", "updated_at"])
    messages.success(request, "Journal photo updated.")
    return redirect(_safe_next_url(request, reverse("journal_entry_detail", args=[entry.pk])))


@verified_member_or_staff_required
def edit_journal_entry(request, entry_id):
    entry = get_object_or_404(
        JournalEntry.objects.select_related("adventure"),
        pk=entry_id,
    )
    adventure = entry.adventure

    if not _can_manage_adventure(request.user, adventure):
        return HttpResponseForbidden(
            "Only the Adventure owner or authorized staff can edit this Journal entry."
        )

    if request.method == "POST":
        submitted_photos = request.FILES.getlist("photos")
        form_data = request.POST.copy()
        form_data.setdefault("operating_callsign", entry.operating_callsign)
        if not form_data.get("location_name") and form_data.get("location"):
            posted_location = visible_locations(request.user).filter(pk=form_data["location"]).first()
            if posted_location:
                form_data["location_name"] = posted_location.name
        form = JournalEntryForm(
            form_data, request.FILES, instance=entry, adventure=adventure, user=request.user
        )

        if form.is_valid():
            with transaction.atomic():
                location = form.resolve_location(request.user)
                entry = form.save(commit=False)
                entry.location = location
                entry.save()

                saved_count, duplicate_count, statuses = _save_entry_photos(
                    entry,
                    [
                        photo for photo in submitted_photos
                        if photo in (form.cleaned_data.get("photos") or [])
                    ],
                )
                adventure.save(update_fields=["updated_at"])


            if saved_count:
                messages.success(
                    request,
                    f"{saved_count} photo{'s' if saved_count != 1 else ''} added to the Journal Entry.",
                )
                add_photo_upload_notice(request, statuses)
            if duplicate_count:
                messages.info(
                    request,
                    f"{duplicate_count} duplicate photo{'s were' if duplicate_count != 1 else ' was'} skipped.",
                )
            _report_rejected_entry_photos(request, form)


            return redirect("journal_entry_detail", entry_id=entry.pk)
    else:
        form = JournalEntryForm(instance=entry, adventure=adventure, user=request.user)

    return render(
        request,
        "adventures/edit_journal_entry.html",
        {
            "adventure": adventure,
            "entry": entry,
            "form": form,
            "can_manage_adventure": True,
            "journal_location_choices": _journal_location_choices(request.user),
            "journal_map_defaults": _journal_map_defaults(adventure, request.user, entry),
        },
    )




def _entry_origin(entry):
    operating_location = None
    location = entry.location or entry.adventure.location

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


@verified_member_or_staff_required
def import_adif(request, entry_id):
    entry = get_object_or_404(
        JournalEntry.objects.select_related(
            "adventure",
            "adventure__location",
            "adventure__operating_location",
        ),
        pk=entry_id,
    )

    if not _can_manage_adventure(request.user, entry.adventure):
        return HttpResponseForbidden(
            "Only the Adventure owner or authorized staff can import contacts."
        )

    return_to = (
        request.POST.get("return_to")
        or request.GET.get("return_to")
        or reverse("journal_entry_detail", args=[entry.pk])
    )
    if not url_has_allowed_host_and_scheme(
        return_to,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return_to = reverse("journal_entry_detail", args=[entry.pk])

    if request.method == "POST":
        form = AdifImportForm(request.POST, request.FILES)

        if form.is_valid():
            uploaded_file = form.cleaned_data["adif_file"]
            latitude, longitude = _entry_origin(entry)
            contacts, invalid_count = parse_adif_bytes_with_counts(
                uploaded_file.read(),
                origin_latitude=latitude,
                origin_longitude=longitude,
            )

            if not contacts:
                form.add_error(
                    "adif_file",
                    "No valid contacts with callsign and QSO date were found.",
                )
            elif len(contacts) > 50000:
                form.add_error(
                    "adif_file",
                    "This import contains more than 50,000 contacts.",
                )
            else:
                token = uuid4().hex
                payload = {
                    "entry_id": entry.pk,
                    "filename": uploaded_file.name,
                    "contacts": [contact.as_dict() for contact in contacts],
                    "invalid_count": invalid_count,
                    "return_to": return_to,
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
            "return_to": return_to,
        },
    )


@verified_member_or_staff_required
def preview_adif_import(request, entry_id, token):
    entry = get_object_or_404(
        JournalEntry.objects.select_related("adventure"),
        pk=entry_id,
    )

    if not _can_manage_adventure(request.user, entry.adventure):
        return HttpResponseForbidden(
            "Only the Adventure owner or authorized staff can preview contacts."
        )

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


@verified_member_or_staff_required
@require_POST
def confirm_adif_import(request, entry_id, token):
    entry = get_object_or_404(
        JournalEntry.objects.select_related("adventure"),
        pk=entry_id,
    )

    if not _can_manage_adventure(request.user, entry.adventure):
        return HttpResponseForbidden(
            "Only the Adventure owner or authorized staff can import contacts."
        )

    if request.session.get("adif_preview_token") != token:
        messages.error(request, "That ADIF preview has expired.")
        return redirect("import_adif", entry_id=entry.pk)

    path = _preview_path(token)

    if not path.exists():
        messages.error(request, "That ADIF preview has expired.")
        return redirect("import_adif", entry_id=entry.pk)

    payload = json.loads(path.read_text(encoding="utf-8"))
    imported_count = 0
    duplicate_count = 0
    invalid_count = payload.get("invalid_count", 0)

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
                    owner=request.user,
                    source=JournalContact.Source.ADIF,
                    station_callsign=entry.operating_callsign or entry.adventure.operating_callsign,
                    operator_callsign=entry.operating_callsign or entry.adventure.operating_callsign,
                    qso_date=date.fromisoformat(contact["qso_date"]),
                    time_on=(
                        time.fromisoformat(contact["time_on"])
                        if contact.get("time_on")
                        else None
                    ),
                    callsign=contact["callsign"],
                    mode=contact.get("mode", ""),
                    band=contact.get("band", ""),
                    frequency=contact.get("frequency"),
                    latitude=contact.get("latitude"),
                    longitude=contact.get("longitude"),
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
        imported_count = len(pending)

    path.unlink(missing_ok=True)
    request.session.pop("adif_preview_token", None)
    entry.adventure.save(update_fields=["updated_at"])

    messages.success(
        request,
        f"{imported_count} contacts imported successfully.",
    )
    if duplicate_count:
        messages.info(
            request,
            f"{duplicate_count} duplicate contact{'s' if duplicate_count != 1 else ''} skipped.",
        )
    if invalid_count:
        messages.info(
            request,
            f"{invalid_count} invalid contact{'s' if invalid_count != 1 else ''} skipped.",
        )

    return redirect("journal_entry_detail", entry_id=entry.pk)


@verified_member_or_staff_required
@require_POST
def cancel_adif_import(request, entry_id, token):
    entry = get_object_or_404(
        JournalEntry.objects.select_related("adventure"),
        pk=entry_id,
    )

    if not _can_manage_adventure(request.user, entry.adventure):
        return HttpResponseForbidden(
            "Only the Adventure owner or authorized staff can cancel this import."
        )

    _preview_path(token).unlink(missing_ok=True)
    request.session.pop("adif_preview_token", None)
    return redirect("import_adif", entry_id=entry.pk)


@verified_member_or_staff_required
@require_POST
def delete_journal_entry(request, entry_id):
    entry = get_object_or_404(
        JournalEntry.objects.select_related("adventure"),
        pk=entry_id,
    )
    adventure = entry.adventure

    if not _can_manage_adventure(request.user, adventure):
        return HttpResponseForbidden(
            "Only the Adventure owner or authorized staff can delete this Journal entry."
        )

    with transaction.atomic():
        deleting_cover = (
            adventure.cover_photo_id is not None
            and entry.photos.filter(pk=adventure.cover_photo_id).exists()
        )

        entry.delete()

        if deleting_cover:
            adventure.cover_photo = None
            adventure.cover_photo_is_explicit = False
            adventure.save(update_fields=["cover_photo", "cover_photo_is_explicit", "updated_at"])
        else:
            adventure.save(update_fields=["updated_at"])

    return redirect("edit_adventure", slug=adventure.slug)


@verified_member_or_staff_required
@require_POST
def make_cover_photo(request, photo_id, slug=None):
    photo = get_object_or_404(
        Photo.objects.select_related("journal_entry__adventure"),
        pk=photo_id,
    )
    adventure = photo.journal_entry.adventure

    if slug is not None and adventure.slug != slug:
        return HttpResponseForbidden(
            "The selected photo does not belong to this Adventure."
        )

    if not _can_manage_adventure(request.user, adventure):
        return HttpResponseForbidden(
            "Only the Adventure owner or authorized staff can change its cover photo."
        )

    if not photo.is_publicly_visible or not photo.journal_entry.is_public:
        return HttpResponseForbidden(
            "Only an approved, publicly eligible Adventure photo can be used as cover."
        )

    adventure.cover_photo = photo
    adventure.cover_photo_is_explicit = True
    adventure.save(update_fields=["cover_photo", "cover_photo_is_explicit", "updated_at"])
    AdventureCoverSelectionAudit.objects.create(
        adventure=adventure, photo=photo, actor=request.user, action="selected"
    )
    messages.success(request, "Adventure cover updated.")
    return redirect(_safe_next_url(request, adventure.get_absolute_url()))


@verified_member_or_staff_required
@require_POST
def delete_photo(request, photo_id):
    photo = get_object_or_404(
        Photo.objects.select_related("journal_entry__adventure"),
        pk=photo_id,
    )
    adventure = photo.journal_entry.adventure

    if not _can_manage_adventure(request.user, adventure):
        return HttpResponseForbidden(
            "Only the Adventure owner or authorized staff can delete this photo."
        )

    entry_id = photo.journal_entry_id
    with transaction.atomic():
        _delete_photo_records([photo])
        adventure.save(update_fields=["updated_at"])
    messages.success(request, "Photo deleted.")
    return redirect("journal_photo_gallery", entry_id=entry_id)


@verified_member_required
@require_POST
def add_comment(request, slug):
    adventure = get_object_or_404(Adventure, slug=slug)
    form = CommentForm(request.POST)

    if form.is_valid():
        comment = form.save(commit=False)
        comment.adventure = adventure
        comment.operator = request.user
        comment.save()

    return redirect(adventure.get_absolute_url())


@verified_member_required
@require_POST
def delete_comment(request, comment_id):
    comment = get_object_or_404(Comment, pk=comment_id)

    if comment.operator != request.user and comment.adventure.owner != request.user:
        return HttpResponseForbidden(
            "Only the comment author or Adventure owner can delete this comment."
        )

    adventure_url = comment.adventure.get_absolute_url()
    comment.delete()
    return redirect(adventure_url)


@verified_member_required
def create_location(request):
    if request.method == "POST":
        location_form = LocationForm(
            request.POST,
            request.FILES,
            prefix="location",
            require_coordinates=True,
            user=request.user,
        )
        location_valid = location_form.is_valid()

        if location_valid:
            with transaction.atomic():
                location = location_form.save(commit=False)
                location.created_by = request.user
                if location.has_operating_advisory:
                    location.advisory_updated_at = timezone.now()
                else:
                    location.operating_advisory = ""
                    location.advisory_updated_at = None
                location.save()
                if request.FILES.get("location-photo"):
                    moderate_location_photo(location)
                    location.refresh_from_db(fields=["photo_moderation_status"])
                    add_photo_upload_notice(request, [location.photo_moderation_status])

            messages.success(request, "Location saved successfully.")
            if request.POST.get("return_to") == "adventure":
                params = {
                    "location": location.pk,
                    "title": request.POST.get("draft_title", ""),
                    "public": request.POST.get("draft_public", "1"),
                }
                return redirect(f"{reverse('add_adventure')}?{urlencode(params)}")
            return redirect("location_detail", location_id=location.pk)
    else:
        initial_location = {}
        map_latitude = request.GET.get("latitude", "").strip()
        map_longitude = request.GET.get("longitude", "").strip()

        if map_latitude and map_longitude:
            initial_location["latitude"] = map_latitude
            initial_location["longitude"] = map_longitude
        location_form = LocationForm(
            prefix="location",
            initial=initial_location,
            require_coordinates=True,
            user=request.user,
        )

    return render(
        request,
        "adventures/create_location.html",
        {
            "location_form": location_form,
            "operating_form": None,
            "page_title": "Add New Location",
            "save_label": "Save Location",
            "editing_location": None,
            "return_to": request.GET.get(
                "return_to",
                request.POST.get("return_to", ""),
            ),
            "draft_title": request.GET.get(
                "title",
                request.POST.get("draft_title", ""),
            ),
            "draft_public": request.GET.get(
                "public",
                request.POST.get("draft_public", "1"),
            ),
            "require_location_pin": True,
        },
    )


@verified_member_or_staff_required
def edit_location(request, location_id):
    location = get_object_or_404(visible_locations(request.user), pk=location_id)
    if not can_manage_location(request.user, location):
        return HttpResponseForbidden(
            "Only the Location owner or authorized staff can edit this Location."
        )
    if request.method == "POST":
        location_form = LocationForm(
            request.POST,
            request.FILES,
            instance=location,
            prefix="location",
            user=request.user,
        )
        if location_form.is_valid():
            location = location_form.save()
            if request.FILES.get("location-photo"):
                moderate_location_photo(location)
                location.refresh_from_db(fields=["photo_moderation_status"])
                add_photo_upload_notice(request, [location.photo_moderation_status])
            return redirect("location_detail", location_id=location.pk)
    else:
        location_form = LocationForm(
            instance=location, prefix="location", user=request.user
        )
    return render(request, "adventures/create_location.html", {
        "location_form": location_form,
        "operating_form": None,
        "page_title": "Edit Location",
        "save_label": "Save Changes",
        "editing_location": location,
        "require_location_pin": False,
    })


@verified_member_required
def add_operating_position(request, location_id):
    location = get_object_or_404(visible_locations(request.user), pk=location_id)
    if request.method == "POST":
        form = OperatingLocationForm(request.POST)
        if form.is_valid():
            position = form.save(commit=False)
            position.location = location
            position.created_by = request.user
            position.save()
            return redirect("location_detail", location_id=location.pk)
    else:
        initial = {}
        if location.latitude is not None and location.longitude is not None:
            initial = {
                "latitude": location.latitude,
                "longitude": location.longitude,
            }
        form = OperatingLocationForm(initial=initial)
    return render(request, "adventures/operating_position_form.html", {
        "location": location,
        "form": form,
        "page_title": "Add Operating Position",
        "editing_position": None,
    })


@verified_member_required
def edit_operating_position(request, position_id):
    position = get_object_or_404(
        OperatingLocation.objects.select_related("location").filter(
            location__in=visible_locations(request.user)
        ),
        pk=position_id,
    )
    if not can_edit_operating_position_pin(request.user, position):
        return HttpResponseForbidden(
            "You are not authorized to edit this Operating Position."
        )
    if request.method == "POST":
        form = OperatingLocationForm(request.POST, instance=position)
        if form.is_valid():
            form.save()
            return redirect("location_detail", location_id=position.location_id)
    else:
        form = OperatingLocationForm(instance=position)
    return render(request, "adventures/operating_position_form.html", {
        "location": position.location,
        "form": form,
        "page_title": "Edit Operating Position",
        "editing_position": position,
    })
