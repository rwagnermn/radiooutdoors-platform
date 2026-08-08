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
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from core.models import Adventure, Comment, JournalContact, JournalEntry, Location, OperatingLocation, Photo
from core.photo_moderation import moderate_location_photo, moderate_photo
from core.photo_upload_notices import add_photo_upload_notice
from core.auth import (
    is_verified_member,
    verified_member_or_staff_required,
    verified_member_required,
)

from .adif_parser import parse_adif_bytes

from .forms import (
    AdifImportForm,
    AdventureForm,
    CommentForm,
    JournalEntryForm,
    LocationForm,
    OperatingLocationForm,
)


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
    first_saved_photo = None
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

        if first_saved_photo is None:
            first_saved_photo = photo

    if adventure.cover_photo_id is None and first_saved_photo is not None:
        adventure.cover_photo = first_saved_photo
        adventure.save(update_fields=["cover_photo", "updated_at"])

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
        adventures = adventures.filter(
            Q(title__icontains=search)
            | Q(location__name__icontains=search)
            | Q(location__city__icontains=search)
            | Q(location__state__icontains=search)
            | Q(owner__username__icontains=search)
        )

    if state:
        adventures = adventures.filter(location__state=state)

    if place:
        adventures = adventures.filter(location_id=place)

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
        Location.objects.exclude(state="")
        .values_list("state", flat=True)
        .distinct()
        .order_by("state")
    )
    locations = Location.objects.all().order_by("name")

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

    if not adventure.is_public and adventure.owner != request.user:
        raise Http404("Adventure not found.")

    journal_entries = adventure.journal_entries.all()
    if adventure.owner != request.user:
        journal_entries = journal_entries.filter(is_public=True)

    adventure_photos = Photo.objects.filter(
        journal_entry__in=journal_entries,
    ).select_related("journal_entry")
    if adventure.owner != request.user and not request.user.is_staff:
        adventure_photos = adventure_photos.filter(
            moderation_status=Photo.ModerationStatus.APPROVED
        )
    contact_count = JournalContact.objects.filter(
        journal_entry__in=journal_entries,
    ).count()

    return render(
        request,
        "adventures/adventure_detail.html",
        {
            "adventure": adventure,
            "journal_entries": journal_entries,
            "adventure_photos": adventure_photos,
            "contact_count": contact_count,
        },
    )


@verified_member_required
@require_POST
def start_adventure_here(request, location_id):
    location = get_object_or_404(Location, pk=location_id)
    operating_location = None
    operating_location_id = request.POST.get("operating_location")

    if operating_location_id:
        operating_location = get_object_or_404(
            location.operating_locations,
            pk=operating_location_id,
        )

    adventure = Adventure.objects.create(
        owner=request.user,
        location=location,
        operating_location=operating_location,
        status=Adventure.Status.ACTIVE,
    )

    return redirect("edit_adventure", slug=adventure.slug)


@verified_member_required
def add_adventure(request):
    selected_location_id = request.GET.get("location")
    selected_operating_id = request.GET.get("operating")
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
                )
                _, _, statuses = _save_entry_photos(entry, uploaded_photos)
                add_photo_upload_notice(request, statuses)
            messages.success(request, "Adventure created successfully.")
            return redirect("all_adventures")
    else:
        initial = {
            "title": draft_title,
            "is_public": draft_public != "0",
        }

        if selected_location_id:
            initial["location"] = selected_location_id

        if selected_operating_id:
            initial["operating_location"] = selected_operating_id

        form = AdventureForm(initial=initial, user=request.user)

        if selected_location_id:
            form.fields["operating_location"].queryset = (
                OperatingLocation.objects.filter(
                    location_id=selected_location_id
                ).order_by("name")
            )

    operating_positions = [
        {
            "id": position.pk,
            "location_id": position.location_id,
            "location_name": position.location.name,
            "name": position.name,
            "latitude": (
                float(position.latitude)
                if position.latitude is not None
                else None
            ),
            "longitude": (
                float(position.longitude)
                if position.longitude is not None
                else None
            ),
        }
        for position in OperatingLocation.objects.select_related("location").order_by(
            "location__name", "name"
        )
    ]
    return render(
        request,
        "adventures/adventure_form.html",
        {
            "form": form,
            "page_title": "Add New Adventure",
            "adventure": None,
            "operating_positions": operating_positions,
        },
    )


@verified_member_required
@require_POST
def create_operating_position_inline(request, location_id):
    location = get_object_or_404(Location, pk=location_id)
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
            adventure = form.save()
            return redirect("edit_adventure", slug=adventure.slug)
    else:
        form = AdventureForm(instance=adventure, user=request.user)

    operating_positions = [
        {
            "id": position.pk,
            "location_id": position.location_id,
            "location_name": position.location.name,
            "name": position.name,
            "latitude": (
                float(position.latitude)
                if position.latitude is not None
                else None
            ),
            "longitude": (
                float(position.longitude)
                if position.longitude is not None
                else None
            ),
        }
        for position in OperatingLocation.objects.select_related("location").order_by(
            "location__name", "name"
        )
    ]
    journal_entries = adventure.journal_entries.prefetch_related("photos").all()

    return render(
        request,
        "adventures/adventure_form.html",
        {
            "form": form,
            "page_title": "Edit Adventure",
            "adventure": adventure,
            "operating_positions": operating_positions,
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


@verified_member_required
def import_adif(request, entry_id):
    entry = get_object_or_404(
        JournalEntry.objects.select_related(
            "adventure",
            "adventure__location",
            "adventure__operating_location",
        ),
        pk=entry_id,
    )

    if entry.adventure.owner != request.user:
        return HttpResponseForbidden(
            "Only the Adventure owner can import contacts."
        )

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
    entry = get_object_or_404(
        JournalEntry.objects.select_related("adventure"),
        pk=entry_id,
    )

    if entry.adventure.owner != request.user:
        return HttpResponseForbidden(
            "Only the Adventure owner can preview contacts."
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


@verified_member_required
@require_POST
def confirm_adif_import(request, entry_id, token):
    entry = get_object_or_404(
        JournalEntry.objects.select_related("adventure"),
        pk=entry_id,
    )

    if entry.adventure.owner != request.user:
        return HttpResponseForbidden(
            "Only the Adventure owner can import contacts."
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
            f"{imported_count} contact"
            f"{'s' if imported_count != 1 else ''} imported."
        ),
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
    entry = get_object_or_404(
        JournalEntry.objects.select_related("adventure"),
        pk=entry_id,
    )

    if entry.adventure.owner != request.user:
        return HttpResponseForbidden(
            "Only the Adventure owner can cancel this import."
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
        replacement = (
            Photo.objects.filter(journal_entry__adventure=adventure)
            .order_by("taken_at", "display_order", "created_at")
            .first()
        )
        adventure.cover_photo = replacement
        adventure.save(update_fields=["cover_photo", "updated_at"])
    else:
        adventure.save(update_fields=["updated_at"])

    return redirect("edit_adventure", slug=adventure.slug)


@verified_member_required
@require_POST
def make_cover_photo(request, photo_id):
    photo = get_object_or_404(
        Photo.objects.select_related("journal_entry__adventure"),
        pk=photo_id,
    )
    adventure = photo.journal_entry.adventure

    if adventure.owner != request.user:
        return HttpResponseForbidden(
            "Only the operator who owns this adventure can change its cover photo."
        )

    adventure.cover_photo = photo
    adventure.save(update_fields=["cover_photo", "updated_at"])
    return redirect("edit_adventure", slug=adventure.slug)


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
        replacement = (
            Photo.objects.filter(journal_entry__adventure=adventure)
            .order_by("taken_at", "display_order", "created_at")
            .first()
        )
        adventure.cover_photo = replacement
        adventure.save(update_fields=["cover_photo", "updated_at"])
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
        )
        operating_form = OperatingLocationForm(
            request.POST,
            prefix="operating",
        )

        location_valid = location_form.is_valid()
        operating_valid = operating_form.is_valid()

        if location_valid and operating_valid:
            with transaction.atomic():
                location = location_form.save(commit=False)
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

                operating_location = operating_form.save(commit=False)
                operating_location.location = location
                operating_location.save()

            messages.success(request, "Location and first Operating Position saved.")
            if request.POST.get("return_to") == "adventure":
                params = {
                    "location": location.pk,
                    "operating": operating_location.pk,
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
        )
        operating_form = OperatingLocationForm(prefix="operating")

    return render(
        request,
        "adventures/create_location.html",
        {
            "location_form": location_form,
            "operating_form": operating_form,
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
        },
    )


@verified_member_required
def edit_location(request, location_id):
    location = get_object_or_404(Location, pk=location_id)
    if request.method == "POST":
        location_form = LocationForm(
            request.POST,
            request.FILES,
            instance=location,
            prefix="location",
        )
        if location_form.is_valid():
            location = location_form.save()
            if request.FILES.get("location-photo"):
                moderate_location_photo(location)
                location.refresh_from_db(fields=["photo_moderation_status"])
                add_photo_upload_notice(request, [location.photo_moderation_status])
            return redirect("location_detail", location_id=location.pk)
    else:
        location_form = LocationForm(instance=location, prefix="location")
    return render(request, "adventures/create_location.html", {
        "location_form": location_form,
        "operating_form": None,
        "page_title": "Edit Location",
        "save_label": "Save Changes",
        "editing_location": location,
    })


@verified_member_required
def add_operating_position(request, location_id):
    location = get_object_or_404(Location, pk=location_id)
    if request.method == "POST":
        form = OperatingLocationForm(request.POST)
        if form.is_valid():
            position = form.save(commit=False)
            position.location = location
            position.save()
            return redirect("location_detail", location_id=location.pk)
    else:
        form = OperatingLocationForm()
    return render(request, "adventures/operating_position_form.html", {
        "location": location,
        "form": form,
    })
