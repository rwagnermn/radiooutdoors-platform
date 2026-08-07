import base64
import hashlib
import random
from datetime import timedelta
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import CommandError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

from .models import (
    Adventure,
    Comment,
    FollowRelationship,
    JournalEntry,
    Location,
    MemberProfile,
    OperatingLocation,
    Photo,
)


DEMO_USERNAME_PREFIX = "demo_"
DEMO_LOCATION_PREFIX = "Demo — "
DEMO_PASSWORD = "RadioDemo123!"
DEMO_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
DEMO_PHOTO_MAX_DIMENSION = 1600

DEMO_USERS = [
    ("demo_anna", "Anna", "Nelson", "anna.demo@example.test", "N0ANA", "Duluth", "MN", "USA"),
    ("demo_bob", "Bob", "Miller", "bob.demo@example.test", "K0BOB", "Cambridge", "MN", "USA"),
    ("demo_carla", "Carla", "Reed", "carla.demo@example.test", "W0CAR", "St. Cloud", "MN", "USA"),
    ("demo_dieter", "Dieter", "Koch", "dieter.demo@example.test", "DL7DEMO", "Hamburg", "", "Germany"),
    ("demo_emily", "Emily", "Hart", "emily.demo@example.test", "VE3EMI", "Thunder Bay", "ON", "Canada"),
    ("demo_frank", "Frank", "Wilson", "frank.demo@example.test", "VK2FRK", "Sydney", "NSW", "Australia"),
]

LOCATION_SPECS = [
    ("Gooseberry Falls State Park", Location.LocationType.PARK, "Two Harbors", "MN", "Trailhead picnic area"),
    ("Burlington Bay Campground", Location.LocationType.CAMPGROUND, "Two Harbors", "MN", "Lakeside campsite"),
    ("Benson Airport", Location.LocationType.OTHER, "Saint Paul", "MN", "Hangar observation area"),
    ("Sherburne National Wildlife Refuge", Location.LocationType.WMA_DNR, "Zimmerman", "MN", "Welcome station lawn"),
    ("Carlos Avery", Location.LocationType.WMA_DNR, "Forest Lake", "MN", "Quiet parking turnout"),
    ("Junction Bowl", Location.LocationType.OTHER, "Isanti", "MN", "Club meeting room"),
]

ADVENTURE_SPECS = [
    ("Sunrise Portable Session", "A quiet county-park setup with a compact station and an early start."),
    ("Cabin Radio Weekend", "A relaxed cabin weekend combining antenna experiments, conversation, and evening operating."),
    ("Field Day Setup and Operation", "A club Field Day effort covering setup, operating shifts, visitors, and teardown."),
    ("Club Antenna and Tower Project", "Members worked together on feed line, supports, safety checks, and antenna adjustments."),
    ("Regional Hamfest Visit", "A day of swap tables, technical conversations, demonstrations, and a few useful finds."),
    ("Lakeside Portable Operating", "Portable HF operating beside the water with changing weather and a low-noise location."),
    ("Airport Radio and Aviation Visit", "An aviation-related outing with portable radio, aircraft watching, and hangar conversation."),
    ("Road-Trip Radio Stop", "A planned operating break during a longer drive, using a fast and practical mobile setup."),
    ("Emergency Communications Exercise", "A realistic communications drill focused on deployment, message handling, and teamwork."),
    ("Youth Radio Demonstration", "A hands-on demonstration introducing young visitors to amateur radio and simple antennas."),
]

JOURNAL_SPECS = [
    (0, "Arrival and site check", "Arrived early, walked the site, and chose a spot with room for the antenna and safe coax routing."),
    (0, "First contacts", "The band opened shortly after setup. A clear first contact confirmed that the portable station was working well."),
    (1, "Cabin antenna setup", "Raised a wire antenna between two trees and kept the feed point clear of the walking path."),
    (1, "Evening operating", "Worked several stations after sunset while everyone compared signal reports around the cabin table."),
    (2, "Field Day setup", "The club crew unloaded shelters, batteries, radios, and feed line before the operating period began."),
    (2, "Visitor at the station", "A visitor stopped to ask how the station worked and completed a short supervised contact."),
    (3, "Tower safety review", "Reviewed the lift plan, checked hardware, and assigned spotters before any tower work started."),
    (3, "Antenna adjustment", "Lowered one end of the antenna, corrected the element length, and confirmed a better match across the band."),
    (4, "Hamfest show-and-tell", "Compared a home-built tuner with two commercial units and picked up a useful grounding idea."),
    (5, "Weather changed", "A lake breeze increased during lunch, so the mast was lowered and guy lines were tightened before operating resumed."),
    (6, "Hangar conversation", "An aircraft owner explained the panel radios while the portable station monitored local activity outside."),
    (7, "Quick roadside setup", "The magnetic loop and battery station were on the air within ten minutes of parking."),
    (8, "Message-handling drill", "Passed practice traffic between teams, found one confusing phrase, and improved the message form."),
    (9, "Youth demonstration", "Visitors practiced phonetics, found stations on the waterfall, and helped log a successful contact."),
    (9, "Teardown and lesson learned", "Packed the station before dark. Next time we will label the short coax jumpers and bring one more ground stake."),
]

DEMO_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def require_development_mode():
    if not settings.DEBUG:
        raise CommandError("Demo-data commands are available only when DEBUG=True.")


def _demo_photo_sources(source_directory):
    source_directory = Path(source_directory)
    if not source_directory.is_dir():
        raise CommandError(f"Source image directory does not exist: {source_directory}")
    return sorted(
        path
        for path in source_directory.rglob("*")
        if path.is_file() and path.suffix.lower() in DEMO_PHOTO_EXTENSIONS
    )


def _optimized_demo_photo(source_path):
    with Image.open(source_path) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode not in {"RGB", "L"}:
            background = Image.new("RGB", image.size, "white")
            if "A" in image.getbands():
                background.paste(image, mask=image.getchannel("A"))
            else:
                background.paste(image)
            image = background
        elif image.mode == "L":
            image = image.convert("RGB")
        image.thumbnail(
            (DEMO_PHOTO_MAX_DIMENSION, DEMO_PHOTO_MAX_DIMENSION),
            Image.Resampling.LANCZOS,
        )
        output = BytesIO()
        image.save(output, format="JPEG", quality=85, optimize=True)
    return output.getvalue()


@transaction.atomic
def populate_demo_photos(source_directory, seed=None):
    """Copy random local images into empty demo Journals and cover slots."""
    require_development_mode()
    source_paths = _demo_photo_sources(source_directory)
    if not source_paths:
        raise CommandError(
            f"No supported images were found under: {Path(source_directory)}"
        )

    missing_entries = list(
        JournalEntry.objects.filter(
            adventure__owner__username__startswith=DEMO_USERNAME_PREFIX,
            photos__isnull=True,
        ).select_related("adventure")
    )
    generator = random.Random(seed) if seed is not None else random.SystemRandom()
    generator.shuffle(source_paths)
    source_cycle = iter(source_paths)
    used_sources = []
    assigned_hashes = set(
        Photo.objects.filter(image__contains="demo-local-")
        .exclude(file_hash="")
        .values_list("file_hash", flat=True)
    )
    assigned_hash_prefixes = {
        Path(name).stem.rsplit("-", 1)[-1]
        for name in Location.objects.exclude(photo="").values_list(
            "photo", flat=True
        )
        if "demo-location-" in name
    }
    journal_count = 0
    cover_count = 0
    skipped_invalid = 0
    skipped_duplicates = 0

    def next_unique_source():
        nonlocal skipped_invalid, skipped_duplicates
        photo_bytes = None
        while photo_bytes is None:
            try:
                source_path = next(source_cycle)
            except StopIteration:
                raise CommandError(
                    "Not enough distinct readable source images for missing demo photos."
                )
            try:
                photo_bytes = _optimized_demo_photo(source_path)
            except (OSError, ValueError, UnidentifiedImageError):
                skipped_invalid += 1
                continue

            digest = hashlib.sha256(photo_bytes).hexdigest()
            if digest in assigned_hashes or digest[:12] in assigned_hash_prefixes:
                skipped_duplicates += 1
                photo_bytes = None
        assigned_hashes.add(digest)
        assigned_hash_prefixes.add(digest[:12])
        used_sources.append(source_path)
        return source_path, photo_bytes, digest

    for entry in missing_entries:
        source_path, photo_bytes, digest = next_unique_source()
        photo = Photo.objects.create(
            journal_entry=entry,
            caption="Development demo photo",
            taken_at=entry.entry_at,
            file_hash=digest,
            moderation_status=Photo.ModerationStatus.APPROVED,
        )
        photo.image.save(
            f"demo-local-{entry.pk}-{digest[:12]}.jpg",
            ContentFile(photo_bytes),
            save=True,
        )
        journal_count += 1

        adventure = entry.adventure
        if adventure.cover_photo_id is None:
            adventure.cover_photo = photo
            adventure.save(update_fields=["cover_photo", "updated_at"])
            cover_count += 1

    demo_locations = list(
        Location.objects.annotate(
            demo_adventure_count=Count(
                "adventures",
                filter=Q(
                    adventures__owner__username__startswith=DEMO_USERNAME_PREFIX
                ),
                distinct=True,
            ),
            genuine_adventure_count=Count(
                "adventures",
                filter=~Q(
                    adventures__owner__username__startswith=DEMO_USERNAME_PREFIX
                ),
                distinct=True,
            ),
        ).filter(
            Q(name__startswith=DEMO_LOCATION_PREFIX)
            | Q(demo_adventure_count__gt=0, genuine_adventure_count=0),
            photo="",
        )
    )
    location_count = 0
    for location in demo_locations:
        source_path, photo_bytes, digest = next_unique_source()
        location.photo.save(
            f"demo-location-{location.pk}-{digest[:12]}.jpg",
            ContentFile(photo_bytes),
            save=True,
        )
        location_count += 1

    return {
        "source_count": len(source_paths),
        "journal_photos": journal_count,
        "adventure_covers": cover_count,
        "location_photos": location_count,
        "skipped_invalid": skipped_invalid,
        "skipped_duplicates": skipped_duplicates,
        "used_sources": used_sources,
    }


def _delete_photo_files(queryset):
    for photo in queryset.only("image"):
        if photo.image:
            photo.image.delete(save=False)


def clear_demo_activity():
    demo_adventures = Adventure.objects.filter(
        owner__username__startswith=DEMO_USERNAME_PREFIX
    )
    _delete_photo_files(Photo.objects.filter(journal_entry__adventure__in=demo_adventures))
    deleted_count, _ = demo_adventures.delete()
    return deleted_count


def _ensure_demo_members():
    User = get_user_model()
    members = []
    now = timezone.now()
    for username, first, last, email, callsign, city, state, country in DEMO_USERS:
        user, _ = User.objects.get_or_create(username=username)
        user.first_name = first
        user.last_name = last
        user.email = email
        user.is_active = True
        user.set_password(DEMO_PASSWORD)
        user.save()

        profile, _ = MemberProfile.objects.get_or_create(user=user)
        profile.callsign = callsign
        profile.display_name = f"{first} {last}"
        profile.home_city = city
        profile.home_state = state
        profile.home_country = country
        profile.profile_is_public = True
        profile.email_visible_to_members = False
        profile.callsign_verified = True
        profile.verification_method = MemberProfile.VerificationMethod.DEVELOPMENT
        profile.verification_at = now
        profile.qrz_verified_at = None
        profile.bio = (
            "Development-only Radio Outdoors profile used to test realistic "
            "Adventures, Journals, following, filtering, and page layouts."
        )
        profile.save()
        members.append((user, profile))
    return members


def _location_and_position(name, location_type, city, state, position_name):
    location = Location.objects.filter(name=name).first()
    if location is None:
        location, _ = Location.objects.get_or_create(
            name=f"{DEMO_LOCATION_PREFIX}{name}",
            defaults={
                "location_type": location_type,
                "city": city,
                "state": state,
                "description": "Development-only location for realistic Radio Outdoors test data.",
            },
        )
    position = location.operating_locations.first()
    if position is None:
        position, _ = OperatingLocation.objects.get_or_create(
            location=location,
            name=position_name,
            defaults={
                "description": "Development-only operating position with room for a portable station.",
                "parking": OperatingLocation.UnknownYesNo.YES,
                "picnic_tables": OperatingLocation.UnknownYesNo.YES,
                "ambient_noise_level": OperatingLocation.AmbientNoise.QUIET,
            },
        )
    return location, position


def _create_member_activity(user, profile, member_index, locations, now):
    adventures = []
    for index, (activity_title, summary) in enumerate(ADVENTURE_SPECS):
        location, position = locations[(index + member_index) % len(locations)]
        started_at = now - timedelta(days=12 + index * 17 + member_index * 3)
        status = Adventure.Status.ACTIVE if index in {0, 3, 7} else Adventure.Status.COMPLETED
        adventure = Adventure.objects.create(
            owner=user,
            title=f"{activity_title} with {profile.callsign}",
            location=location,
            operating_location=position,
            status=status,
            is_public=index not in {4, 9},
            summary=summary,
            lessons_learned=(
                "Keep the setup simple, label the small cables, and allow more time for teardown."
                if index % 3 == 0
                else ""
            ),
            started_at=started_at,
            completed_at=(started_at + timedelta(hours=8) if status == Adventure.Status.COMPLETED else None),
        )
        if index in {3, 7}:
            Adventure.objects.filter(pk=adventure.pk).update(
                updated_at=started_at + timedelta(hours=10)
            )
        adventures.append(adventure)

    journal_entries = []
    for journal_index, (adventure_index, title, body) in enumerate(JOURNAL_SPECS):
        adventure = adventures[adventure_index]
        entry = JournalEntry.objects.create(
            adventure=adventure,
            title=title,
            body=body,
            entry_at=adventure.started_at + timedelta(hours=journal_index % 5 + 1),
            is_public=journal_index not in {4, 13},
            radio=["IC-705", "FT-891", "KX3", "TM-V71A"][journal_index % 4],
            antenna=["linked dipole", "end-fed half wave", "magnetic loop", "mobile whip"][journal_index % 4],
            portable=adventure_index in {0, 1, 5, 7, 9},
            field_day=adventure_index == 2,
            club_event=adventure_index in {2, 3, 8, 9},
            contest=adventure_index == 2,
            mode_ssb=True,
            mode_cw=journal_index % 4 == 0,
            mode_digital=journal_index % 5 == 0,
        )
        journal_entries.append(entry)

        if journal_index in {2, 7, 12}:
            photo = Photo.objects.create(
                journal_entry=entry,
                caption={
                    2: "Portable station ready for the first contact",
                    7: "Antenna work in progress",
                    12: "Practice message station",
                }[journal_index],
                taken_at=entry.entry_at,
                moderation_status=Photo.ModerationStatus.APPROVED,
            )
            photo.image.save(
                f"demo-{user.username}-{journal_index}.png",
                ContentFile(DEMO_PNG),
                save=True,
            )
            if adventure.cover_photo_id is None:
                adventure.cover_photo = photo
                adventure.save(update_fields=["cover_photo"])

    return adventures, journal_entries


@transaction.atomic
def create_demo_data():
    require_development_mode()
    clear_demo_activity()
    members = _ensure_demo_members()
    locations = [_location_and_position(*spec) for spec in LOCATION_SPECS]
    now = timezone.now().replace(minute=0, second=0, microsecond=0)
    created = []

    for member_index, (user, profile) in enumerate(members):
        adventures, journals = _create_member_activity(
            user, profile, member_index, locations, now
        )
        created.append((profile.callsign, len(adventures), len(journals)))

    for index, (user, _) in enumerate(members):
        followed_profile = members[(index + 1) % len(members)][1]
        relationship, _ = FollowRelationship.objects.get_or_create(
            member=followed_profile,
            follower=user,
        )
        relationship.status = FollowRelationship.Status.APPROVED
        relationship.responded_at = now - timedelta(days=index)
        relationship.save()
        Comment.objects.create(
            adventure=user.adventures.order_by("started_at").first(),
            operator=members[(index + 2) % len(members)][0],
            body="Great notes. This gives me a useful idea for our next club outing.",
        )

    return created


@transaction.atomic
def remove_demo_data():
    require_development_mode()
    User = get_user_model()
    demo_users = User.objects.filter(username__startswith=DEMO_USERNAME_PREFIX)
    _delete_photo_files(Photo.objects.filter(journal_entry__adventure__owner__in=demo_users))
    deleted_users = demo_users.count()
    demo_users.delete()
    demo_locations = Location.objects.filter(
        name__startswith=DEMO_LOCATION_PREFIX,
        adventures__isnull=True,
    )
    deleted_locations = demo_locations.count()
    demo_locations.delete()
    return deleted_users, deleted_locations
