from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.utils import timezone

from PIL import Image
from datetime import date, datetime, time
import hashlib
import json
import logging
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from core.models import (
    Adventure, AdventureCoverSelectionAudit, Comment, JournalContact,
    JournalEntry, Location, OperatingLocation, Photo,
)
from core.photo_moderation import moderate_location_photo, moderate_photo
from core.photo_upload_notices import add_photo_upload_notice
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

from .adif_parser import parse_adif_bytes
from .contact_map import build_contact_map

from .forms import (
    AdifImportForm,
    AdventureForm,
    CommentForm,
    JournalEntryForm,
    LocationForm,
    OperatingLocationForm,
)


logger = logging.getLogger(__name__)


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


@verified_member_required
def my_adventures(request):
    adventures = (
        Adventure.objects.filter(owner=request.user)
        .select_related("location", "operating_location", "cover_photo")
        .annotate(
            journal_count=Count("journal_entries", distinct=True),
            photo_count=Count("journal_entries__photos", distinct=True),
            comment_count=Count("comments", distinct=True),
        )
        .order_by("status", "-updated_at")
    )
    if request.GET.get("source") == "pota":
        adventures = adventures.filter(pota_import__isnull=False)
    adventures = mark_adventure_location_visibility(adventures, request.user)

    return render(
        request,
        "adventures/my_adventures.html",
        {"adventures": adventures},
    )


def all_adventures(request):
    adventures = (
        Adventure.objects.select_related(
            "owner",
            "location",
            "operating_location",
            "cover_photo",
        )
        .annotate(
            journal_count=Count("journal_entries", distinct=True),
            photo_count=Count("journal_entries__photos", distinct=True),
            comment_count=Count("comments", distinct=True),
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
            Q(location__name__icontains=search)
            | Q(location__city__icontains=search)
            | Q(location__state__icontains=search)
        ) & location_access_q(request.user, "location__")
        adventures = adventures.filter(
            Q(title__icontains=search)
            | Q(owner__username__icontains=search)
            | location_search
        )

    if state:
        adventures = adventures.filter(
            location_access_q(request.user, "location__"), location__state=state
        )

    if place:
        adventures = adventures.filter(
            location_access_q(request.user, "location__"), location_id=place
        )

    if activity in {"open", "operating", "progress"}:
        adventures = adventures.filter(status=Adventure.Status.ACTIVE)
    elif activity == "complete":
        adventures = adventures.filter(
            status=Adventure.Status.COMPLETED,
        )

    if sort == "state":
        adventures = adventures.order_by(
            "location__state",
            "location__name",
            "-started_at",
        )
    elif sort == "place":
        adventures = adventures.order_by(
            "location__name",
            "-started_at",
        )
    else:
        adventures = adventures.order_by("-started_at", "-updated_at")

    states = (
        visible_locations(request.user).exclude(state="")
        .values_list("state", flat=True)
        .distinct()
        .order_by("state")
    )
    locations = visible_locations(request.user).order_by("name")
    adventures = mark_adventure_location_visibility(adventures, request.user)

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

    adventure_photos = Photo.objects.filter(
        journal_entry__in=journal_entries,
    ).select_related("journal_entry")
    if adventure.owner != request.user and not request.user.is_staff:
        adventure_photos = adventure_photos.filter(
            moderation_status=Photo.ModerationStatus.APPROVED
        )
    contacts = list(JournalContact.objects.filter(
        journal_entry__in=journal_entries,
    ).select_related("journal_entry"))
    contact_count = len(contacts)
    contact_map = build_contact_map(adventure, contacts, request.user)
    can_manage_journals = bool(
        request.user == adventure.owner and is_verified_member(request.user)
    )
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
    display_cover_photo = adventure.display_cover_photo
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
            "journal_entries": journal_entries,
            "adventure_photos": adventure_photos,
            "contact_count": contact_count,
            "contact_map": contact_map,
            "contact_map_dom_id": "adventure-contact-map",
            "contact_map_data_id": "adventure-contact-map-data",
            "can_manage_adventure": can_manage_adventure,
            "can_manage_journals": can_manage_journals,
            "photo_add_url": photo_add_url,
            "can_view_adventure_location": can_view_adventure_location,
            "display_cover_photo": display_cover_photo,
        },
    )


def adventure_contacts(request, slug):
    adventure = get_object_or_404(
        Adventure.objects.select_related("owner", "location"),
        slug=slug,
    )
    can_manage_adventure = _can_manage_adventure(request.user, adventure)
    if not adventure.is_public and not can_manage_adventure:
        raise Http404("Adventure not found.")

    journal_entries = adventure.journal_entries.annotate(
        aggregated_contact_count=Count("contacts")
    ).order_by("-entry_at", "-pk")
    if not can_manage_adventure:
        journal_entries = journal_entries.filter(is_public=True)

    contacts = list(JournalContact.objects.filter(
        journal_entry__in=journal_entries,
    ).select_related("journal_entry").order_by(
        "-qso_date", "-time_on", "callsign"
    ))
    contact_map = build_contact_map(adventure, contacts, request.user)
    return render(
        request,
        "adventures/adventure_contacts.html",
        {
            "adventure": adventure,
            "journal_entries": journal_entries,
            "contacts": contacts,
            "contact_count": len(contacts),
            "contact_map": contact_map,
            "contact_map_dom_id": "contact-hub-map",
            "contact_map_data_id": "contact-hub-map-data",
            "can_manage_adventure": can_manage_adventure,
        },
    )


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
    selected_location_id = request.GET.get("location")
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
        form = AdventureForm(form_data, request.FILES, user=request.user)

        if form.is_valid():
            try:
                with transaction.atomic():
                    adventure = form.save(commit=False)
                    adventure.owner = request.user
                    adventure.status = Adventure.Status.ACTIVE
                    adventure.save()
                    uploaded_photos = request.FILES.getlist("photos")
                    if uploaded_photos:
                        entry = JournalEntry.objects.create(
                            adventure=adventure,
                            operating_callsign=adventure.operating_callsign,
                            entry_at=timezone.now(),
                            title="Adventure photos",
                            body="Photos from this Adventure.",
                            is_public=adventure.is_public,
                            is_adventure_photo_collection=True,
                        )
                        _, _, statuses = _save_entry_photos(entry, uploaded_photos)
                        add_photo_upload_notice(request, statuses)
            except Exception as exc:
                logger.exception(
                    "Adventure create transaction failed user_id=%s exception=%s",
                    request.user.pk,
                    type(exc).__name__,
                )
                form.add_error(
                    None,
                    "The Adventure could not be saved. Correct any related Location "
                    "or photo errors and try again.",
                )
            else:
                messages.success(request, "Adventure saved successfully.")
                return redirect("my_adventures")
    else:
        initial = {
            "title": draft_title,
            "is_public": draft_public != "0",
        }

        if selected_location_id:
            initial["location"] = selected_location_id

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
        return JsonResponse({"errors": form.errors.get_json_data()}, status=400)

    if (
        form.cleaned_data["latitude"] is None
        or form.cleaned_data["longitude"] is None
    ):
        return JsonResponse(
            {"errors": {"coordinates": [{"message": "Choose a point on the map."}]}},
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
                    "The Adventure could not be saved. Correct any related Location "
                    "errors and try again.",
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



@verified_member_required
@require_POST
def toggle_adventure_visibility(request, slug):
    adventure = get_object_or_404(
        Adventure,
        slug=slug,
        owner=request.user,
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


@verified_member_required
@require_POST
def toggle_journal_visibility(request, entry_id):
    entry = get_object_or_404(
        JournalEntry.objects.select_related("adventure"),
        pk=entry_id,
    )

    if entry.adventure.owner != request.user:
        return HttpResponseForbidden(
            "Only the Adventure owner can change Journal visibility."
        )

    entry.is_public = not entry.is_public
    entry.save(update_fields=["is_public", "updated_at"])
    entry.adventure.save(update_fields=["updated_at"])
    return redirect("journal_entry_detail", entry_id=entry.pk)


@verified_member_required
@require_POST
def delete_selected_contacts(request, entry_id):
    entry = get_object_or_404(
        JournalEntry.objects.select_related("adventure"),
        pk=entry_id,
    )

    if entry.adventure.owner != request.user:
        return HttpResponseForbidden(
            "Only the Adventure owner can delete contacts."
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


@verified_member_required
def add_journal_entry(request, slug):
    adventure = get_object_or_404(Adventure, slug=slug)

    if adventure.owner != request.user:
        return HttpResponseForbidden(
            "Only the operator who owns this adventure can add journal entries."
        )

    if request.method == "POST":
        form_data = request.POST.copy()
        form_data.setdefault("operating_callsign", adventure.operating_callsign)
        if (
            "journal_visibility_present" not in form_data
            and "is_public" not in form_data
        ):
            form_data["is_public"] = "on"
        form = JournalEntryForm(form_data, request.FILES, adventure=adventure)

        if form.is_valid():
            entry = form.save(commit=False)
            entry.adventure = adventure
            entry.save()

            saved_count, duplicate_count, statuses = _save_entry_photos(
                entry,
                request.FILES.getlist("photos"),
            )


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


            adventure.save(update_fields=["updated_at"])
            if request.POST.get("return_to_contacts") == "1":
                messages.success(
                    request,
                    f"Journal Entry created: {entry.title or 'Journal Entry'}.",
                )
                return redirect("adventure_import_contacts", slug=adventure.slug)
            return redirect("journal_entry_detail", entry_id=entry.pk)
    else:
        last_entry = adventure.journal_entries.order_by("-entry_at").first()
        initial = {"operating_callsign": adventure.operating_callsign}

        if last_entry:
            initial = {
                "operating_callsign": adventure.operating_callsign,
                "radio": last_entry.radio,
                "antenna": last_entry.antenna,
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

        form = JournalEntryForm(initial=initial, adventure=adventure)

    return render(
        request,
        "adventures/add_journal_entry.html",
        {
            "adventure": adventure,
            "form": form,
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
        ).prefetch_related("photos", "contacts"),
        pk=entry_id,
    )

    if entry.adventure.owner != request.user and (not entry.adventure.is_public or not entry.is_public):
        raise Http404("Journal Entry not found.")

    contacts = entry.contacts.order_by("-qso_date", "-time_on", "callsign")
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
        },
    )


@verified_member_required
def edit_journal_entry(request, entry_id):
    entry = get_object_or_404(
        JournalEntry.objects.select_related("adventure"),
        pk=entry_id,
    )
    adventure = entry.adventure

    if adventure.owner != request.user:
        return HttpResponseForbidden(
            "Only the operator who owns this adventure can edit this journal entry."
        )

    if request.method == "POST":
        form_data = request.POST.copy()
        form_data.setdefault("operating_callsign", entry.operating_callsign)
        form = JournalEntryForm(
            form_data, request.FILES, instance=entry, adventure=adventure
        )

        if form.is_valid():
            entry = form.save()

            saved_count, duplicate_count, statuses = _save_entry_photos(
                entry,
                request.FILES.getlist("photos"),
            )


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


            adventure.save(update_fields=["updated_at"])
            return redirect("journal_entry_detail", entry_id=entry.pk)
    else:
        form = JournalEntryForm(instance=entry, adventure=adventure)

    return render(
        request,
        "adventures/edit_journal_entry.html",
        {
            "adventure": adventure,
            "entry": entry,
            "form": form,
        },
    )




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
        (
            f"{imported_count} imported; {duplicate_count} skipped; "
            f"{duplicate_count} duplicate{'s' if duplicate_count != 1 else ''}. "
            f"Destination Journal: {entry.title or 'Journal Entry'}."
        ),
    )

    return redirect(payload.get("return_to") or reverse(
        "journal_entry_detail", args=[entry.pk]
    ))


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


@verified_member_required
@require_POST
def delete_journal_entry(request, entry_id):
    entry = get_object_or_404(
        JournalEntry.objects.select_related("adventure"),
        pk=entry_id,
    )
    adventure = entry.adventure

    if adventure.owner != request.user:
        return HttpResponseForbidden(
            "Only the operator who owns this adventure can delete this journal entry."
        )

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


@verified_member_required
@require_POST
def delete_photo(request, photo_id):
    photo = get_object_or_404(
        Photo.objects.select_related("journal_entry__adventure"),
        pk=photo_id,
    )
    adventure = photo.journal_entry.adventure

    if adventure.owner != request.user:
        return HttpResponseForbidden(
            "Only the operator who owns this adventure can delete this photo."
        )

    was_cover = adventure.cover_photo_id == photo.pk
    photo.delete()

    if was_cover:
        adventure.cover_photo = None
        adventure.cover_photo_is_explicit = False
        adventure.save(update_fields=["cover_photo", "cover_photo_is_explicit", "updated_at"])
    else:
        adventure.save(update_fields=["updated_at"])

    return redirect("edit_adventure", slug=adventure.slug)


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
