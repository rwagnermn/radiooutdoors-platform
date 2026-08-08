from django.db.models import Count, Q
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from .models import Adventure, Location, LocationType, OperatingLocation
from .auth import is_verified_member


def _visible_adventure_q(request, prefix=""):
    visibility = Q(**{f"{prefix}is_public": True})
    if request.user.is_authenticated:
        visibility |= Q(**{f"{prefix}owner": request.user})
    return visibility


def home(request):
    featured_location = Location.objects.first()
    featured_adventures = Adventure.objects.filter(
        status=Adventure.Status.COMPLETED,
        is_public=True,
    ).order_by("-completed_at", "-updated_at")[:3]

    return render(
        request,
        "core/home.html",
        {
            "featured_location": featured_location,
            "featured_adventures": featured_adventures,
        },
    )


def location_list(request):
    locations = (
        Location.objects.annotate(
            operating_location_count=Count(
                "operating_locations",
                distinct=True,
            ),
            adventure_count=Count(
                "adventures",
                filter=_visible_adventure_q(request, "adventures__"),
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
        Location.objects.exclude(state="")
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
        Location.objects.select_related("location_type_record").prefetch_related(
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
        Location.objects.annotate(
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
        visible_adventures = location.adventures.filter(_visible_adventure_q(request))

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

            if (
                not cover_photo_url
                and latest_adventure.cover_photo_id
                and latest_adventure.cover_photo.is_publicly_visible
            ):
                cover_photo_url = latest_adventure.cover_photo.image.url

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
        }

        unassigned_open_adventure = any(
            adventure.status == Adventure.Status.ACTIVE
            for adventure in visible_adventures.filter(
                operating_location__isnull=True
            )
        )

        if (
            unassigned_open_adventure
            and location.latitude is not None
            and location.longitude is not None
        ):
            map_points.append(
                {
                    **shared,
                    "has_open_adventure": True,
                    "kind": "location",
                    "operating_location_id": None,
                    "latitude": float(location.latitude),
                    "longitude": float(location.longitude),
                    "title": location.name,
                    "subtitle": location.get_location_type_display(),
                }
            )

        for operating_location in location.operating_locations.all():
            if (
                operating_location.latitude is None
                or operating_location.longitude is None
            ):
                continue

            position_has_open_adventure = any(
                adventure.status == Adventure.Status.ACTIVE
                for adventure in visible_adventures.filter(
                    operating_location=operating_location
                )
            )

            map_points.append(
                {
                    **shared,
                    "has_open_adventure": position_has_open_adventure,
                    "kind": "operating",
                    "operating_location_id": operating_location.pk,
                    "latitude": float(operating_location.latitude),
                    "longitude": float(operating_location.longitude),
                    "title": operating_location.name,
                    "subtitle": location.name,
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

