from django.db.models import Count, Q
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.urls import reverse

from adventures.pota_aggregation import public_pota_leaders

from .models import (
    Adventure,
    Location,
    LocationType,
    OperatingLocation,
)
from .auth import is_verified_member
from .pin_permissions import can_edit_location_pin, can_edit_operating_position_pin
from .location_privacy import can_view_location, mark_adventure_location_visibility, visible_locations


def _visible_adventure_q(request, prefix=""):
    visibility = Q(**{f"{prefix}is_public": True})
    if request.user.is_authenticated:
        visibility |= Q(**{f"{prefix}owner": request.user})
    return visibility


def _visible_journal_q(request, prefix=""):
    if request.user.is_staff:
        return Q()
    visibility = Q(
        **{
            f"{prefix}is_public": True,
            f"{prefix}adventure__is_public": True,
        }
    )
    if request.user.is_authenticated:
        visibility |= Q(**{f"{prefix}adventure__owner": request.user})
    return visibility


def home(request):
    featured_location = visible_locations(request.user).first()
    featured_adventures = Adventure.objects.filter(
        status=Adventure.Status.COMPLETED,
        is_public=True,
    ).order_by("-completed_at", "-updated_at")[:3]

    featured_adventures = mark_adventure_location_visibility(
        featured_adventures, request.user
    )
    return render(
        request,
        "core/home.html",
        {
            "featured_location": featured_location,
            "featured_adventures": featured_adventures,
        },
    )


def pota_leaderboard(request):
    current_year = timezone.localdate().year
    selected_period = (
        "current" if request.GET.get("period") == "current" else "all"
    )
    leaders = list(
        public_pota_leaders(
            activation_year=current_year if selected_period == "current" else None
        )
    )
    podium_classes = ("gold", "silver", "bronze")
    for rank, leader in enumerate(leaders, start=1):
        leader["rank"] = rank
        leader["podium_class"] = podium_classes[rank - 1] if rank <= 3 else ""
    return render(
        request,
        "core/pota_leaderboard.html",
        {
            "leaders": leaders,
            "current_year": current_year,
            "selected_period": selected_period,
            "period_label": (
                str(current_year) if selected_period == "current" else "All Time"
            ),
        },
    )


def location_list(request):
    locations = (
        visible_locations(request.user).annotate(
            operating_location_count=Count(
                "operating_locations",
                distinct=True,
            ),
            journal_use_count=Count(
                "journal_entries",
                filter=Q(
                    journal_entries__is_adventure_photo_collection=False,
                )
                & _visible_journal_q(request, "journal_entries__"),
                distinct=True,
            ),
        )
        .order_by("name")
    )

    search = request.GET.get("q", "").strip()
    state = request.GET.get("state", "").strip()
    location_type = request.GET.get("type", "").strip()

    if search:
        locations = locations.filter(
            Q(name__icontains=search)
            | Q(street_address__icontains=search)
            | Q(address_line_2__icontains=search)
            | Q(city__icontains=search)
            | Q(state__icontains=search)
            | Q(postal_code__icontains=search)
            | Q(reference_code__icontains=search)
            | Q(description__icontains=search)
        )

    if state:
        locations = locations.filter(state=state)

    if location_type:
        locations = locations.filter(
            Q(location_type_record__key=location_type)
            | Q(location_type_record__isnull=True, location_type=location_type)
        )

    states = (
        visible_locations(request.user).exclude(state="")
        .values_list("state", flat=True)
        .distinct()
        .order_by("state")
    )

    return render(
        request,
        "core/location_list.html",
        {
            "locations": locations,
            "states": states,
            "location_types": [
                (item.key, item.name + (" (Inactive)" if not item.is_active else ""))
                for item in LocationType.objects.annotate(
                    location_count=Count("locations")
                ).filter(
                    Q(is_active=True) | Q(location_count__gt=0)
                ).order_by(Lower("name"))
            ],
            "search": search,
            "selected_state": state,
            "selected_type": location_type,
        },
    )


def location_detail(request, location_id):
    location = get_object_or_404(
        visible_locations(request.user).select_related("location_type_record").prefetch_related(
            "operating_locations",
            "adventures__owner",
            "adventures__cover_photo",
        ),
        pk=location_id,
    )

    adventures = (
        location.adventures.filter(
            _visible_adventure_q(request)
        ).select_related(
            "owner",
            "cover_photo",
            "operating_location",
        )
        .annotate(
            journal_count=Count("journal_entries", distinct=True),
            photo_count=Count(
                "journal_entries__photos",
                distinct=True,
            ),
            comment_count=Count("comments", distinct=True),
        )
        .order_by("-started_at")
    )

    return render(
        request,
        "core/location_detail.html",
        {
            "location": location,
            "adventures": adventures,
            "can_edit_location_pin": can_edit_location_pin(request.user, location),
            "single_location_map_data": (
                {
                    "name": location.name,
                    "latitude": float(location.latitude),
                    "longitude": float(location.longitude),
                }
                if location.latitude is not None and location.longitude is not None
                else None
            ),
            "editable_position_ids": [
                position.pk
                for position in location.operating_locations.all()
                if can_edit_operating_position_pin(request.user, position)
            ],
            "is_private_location": location.is_private,
        },
    )


def member_adventures(request):
    return render(
        request,
        "core/coming_soon.html",
        {
            "title": "Member Adventures",
        },
    )


def members(request):
    return render(
        request,
        "core/coming_soon.html",
        {
            "title": "Members",
        },
    )


def learn(request):
    return render(
        request,
        "core/coming_soon.html",
        {
            "title": "Learn",
        },
    )


def about(request):
    return render(request, "core/about.html")


def map_explorer(request):
    locations = (
        visible_locations(request.user).exclude(
            description__startswith="Created from POTA Hunter Log import."
        ).annotate(
            adventure_count=Count("adventures", distinct=True),
        )
        .select_related("location_type_record")
        .prefetch_related(
            "operating_locations",
            "adventures__owner",
            "adventures__cover_photo",
        )
        .order_by("name")
    )

    map_points = []

    for location in locations:
        visible_adventures = Adventure.objects.filter(
            Q(location=location) | Q(journal_entries__location=location)
        ).filter(_visible_adventure_q(request)).distinct()

        latest_adventure = (
            visible_adventures.select_related(
                "owner",
                "cover_photo",
            )
            .order_by("-updated_at")
            .first()
        )

        has_open_adventure = any(
            adventure.status == Adventure.Status.ACTIVE
            for adventure in visible_adventures
        )
        cover_photo_url = location.display_photo_url
        latest_title = ""
        latest_status = ""
        latest_updated = ""
        latest_url = ""

        if latest_adventure is not None:
            latest_title = latest_adventure.title
            latest_status = latest_adventure.display_status_label
            latest_updated = latest_adventure.updated_at.isoformat()
            latest_url = latest_adventure.get_absolute_url()

            resolved_cover = latest_adventure.display_cover_photo
            if not cover_photo_url and resolved_cover:
                cover_photo_url = resolved_cover.public_thumbnail_url

        shared = {
            "location_id": location.pk,
            "location_name": location.name,
            "location_type": location.get_location_type_display(),
            "state": location.state,
            "adventure_count": visible_adventures.count(),
            "has_open_adventure": has_open_adventure,
            "has_operating_advisory": location.has_operating_advisory,
            "operating_advisory": location.operating_advisory,
            "cover_photo_url": cover_photo_url,
            "latest_title": latest_title,
            "latest_status": latest_status,
            "latest_updated": latest_updated,
            "latest_url": latest_url,
            "url": f"/locations/{location.pk}/",
            "start_adventure_url": reverse(
                "start_adventure_here",
                kwargs={"location_id": location.pk},
            ),
            "can_start_adventure": is_verified_member(request.user),
            "can_edit_location_pin": can_edit_location_pin(request.user, location),
            "is_private": location.is_private,
            "location_pin_edit_url": (
                reverse("edit_owned_pin_position", args=["location", location.pk])
                + "?next=" + reverse("map_explorer")
            ) if can_edit_location_pin(request.user, location) else "",
        }

        # The normal workflow exposes exactly one marker per Location. For
        # legacy Locations that have not yet received Location-level
        # coordinates, use the first stored Operating Position coordinate as a
        # display-only fallback. Historical records are never rewritten here.
        latitude = location.latitude
        longitude = location.longitude
        coordinate_source = "location"
        if latitude is None or longitude is None:
            fallback = next(
                (
                    position
                    for position in location.operating_locations.all()
                    if position.latitude is not None
                    and position.longitude is not None
                ),
                None,
            )
            if fallback is not None:
                latitude = fallback.latitude
                longitude = fallback.longitude
                coordinate_source = "legacy_operating_position_fallback"

        if latitude is not None and longitude is not None:
            map_points.append(
                {
                    **shared,
                    "marker_type": "location",
                    "latitude": float(latitude),
                    "longitude": float(longitude),
                    "coordinate_source": coordinate_source,
                    "has_entered_address": bool(location.street_address.strip()),
                    "title": location.name,
                    "subtitle": location.get_location_type_display(),
                    "can_edit_pin": shared["can_edit_location_pin"],
                    "pin_edit_url": shared["location_pin_edit_url"],
                }
            )

    return render(
        request,
        "core/map_explorer.html",
        {
            "map_points": map_points,
            "point_count": len(map_points),
        },
    )
