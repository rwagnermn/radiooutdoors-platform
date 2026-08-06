from datetime import timedelta

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


class Location(models.Model):
    class LocationType(models.TextChoices):
        PARK = "park", "Park"
        CAMPGROUND = "campground", "Campground"
        TRAIL = "trail", "Trail"
        BOAT_LAUNCH = "boat_launch", "Boat Launch"
        SCENIC_OVERLOOK = "scenic_overlook", "Scenic Overlook"
        BEACH = "beach", "Beach"
        CABIN = "cabin", "Cabin"
        BACKYARD = "backyard", "Backyard"
        SUMMIT = "summit", "Summit"
        ISLAND = "island", "Island"
        REST_AREA = "rest_area", "Rest Area"
        WMA_DNR = "wma_dnr", "WMA / DNR Wildlife Management Land"
        OTHER = "other", "Other"

    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=180, unique=True, blank=True)
    location_type = models.CharField(max_length=30, choices=LocationType.choices, default=LocationType.OTHER)
    street_address = models.CharField(max_length=160, blank=True)
    address_line_2 = models.CharField(max_length=160, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=50, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=50, default="USA")
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    official_website = models.URLField(
        blank=True,
        help_text="Official park, campground, government, or location website.",
    )
    reference_code = models.CharField(
        max_length=100,
        blank=True,
        help_text="Optional POTA, WWFF, park, airport, or other reference.",
    )
    description = models.TextField(blank=True)
    has_operating_advisory = models.BooleanField(
        default=False,
        help_text="Show this Location with a red map pin.",
    )
    operating_advisory = models.TextField(
        blank=True,
        help_text="What should another operator know before making the trip?",
    )
    advisory_updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name) or "location"
            slug = base_slug
            counter = 2
            while Location.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class OperatingLocation(models.Model):
    class UnknownYesNo(models.TextChoices):
        UNKNOWN = "unknown", "Unknown"
        YES = "yes", "Yes"
        NO = "no", "No"

    class CellBars(models.IntegerChoices):
        UNKNOWN = 0, "Unknown"
        ONE = 1, "1 Bar"
        TWO = 2, "2 Bars"
        THREE = 3, "3 Bars"
        FOUR = 4, "4 Bars"
        FIVE = 5, "5 Bars"

    class AmbientNoise(models.TextChoices):
        UNKNOWN = "unknown", "Unknown"
        VERY_QUIET = "very_quiet", "Very Quiet"
        QUIET = "quiet", "Quiet"
        MODERATE = "moderate", "Moderate"
        BUSY = "busy", "Busy"
        VERY_BUSY = "very_busy", "Very Busy"

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="operating_locations")
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    parking = models.CharField(max_length=10, choices=UnknownYesNo.choices, default=UnknownYesNo.UNKNOWN)
    restrooms = models.CharField(max_length=10, choices=UnknownYesNo.choices, default=UnknownYesNo.UNKNOWN)
    picnic_tables = models.CharField(max_length=10, choices=UnknownYesNo.choices, default=UnknownYesNo.UNKNOWN)
    shelter = models.CharField(max_length=10, choices=UnknownYesNo.choices, default=UnknownYesNo.UNKNOWN)
    shade = models.CharField(max_length=10, choices=UnknownYesNo.choices, default=UnknownYesNo.UNKNOWN)
    power = models.CharField(max_length=10, choices=UnknownYesNo.choices, default=UnknownYesNo.UNKNOWN)
    drinking_water = models.CharField(max_length=10, choices=UnknownYesNo.choices, default=UnknownYesNo.UNKNOWN)
    cell_coverage_bars = models.PositiveSmallIntegerField(choices=CellBars.choices, default=CellBars.UNKNOWN)
    ambient_noise_level = models.CharField(max_length=20, choices=AmbientNoise.choices, default=AmbientNoise.UNKNOWN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["location__name", "name"]
        constraints = [models.UniqueConstraint(fields=["location", "name"], name="unique_operating_location_name_per_location")]

    def __str__(self):
        return f"{self.location}: {self.name}"


class Adventure(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="adventures")
    title = models.CharField(max_length=180, blank=True)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, related_name="adventures")
    operating_location = models.ForeignKey(OperatingLocation, on_delete=models.SET_NULL, null=True, blank=True, related_name="adventures")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    is_public = models.BooleanField(default=True, help_text="Visible to everyone. Turn this off to keep the Adventure private.")
    summary = models.TextField(
        blank=True,
        help_text="A short overview of the whole Adventure.",
    )
    lessons_learned = models.TextField(
        blank=True,
        help_text="What should you remember for next time?",
    )
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    cover_photo = models.ForeignKey("Photo", on_delete=models.SET_NULL, null=True, blank=True, related_name="cover_for_adventures")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def save(self, *args, **kwargs):
        if not self.title:
            local_date = timezone.localtime(self.started_at).date()
            self.title = f"Adventure - {local_date.strftime('%B %d, %Y')}"
        if not self.slug:
            base_slug = slugify(self.title) or "adventure"
            slug = base_slug
            counter = 2
            while Adventure.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        if self.status == self.Status.COMPLETED and self.completed_at is None:
            self.completed_at = timezone.now()
        elif self.status == self.Status.ACTIVE:
            self.completed_at = None
        super().save(*args, **kwargs)

    @property
    def display_status_key(self):
        if self.status == self.Status.COMPLETED:
            return "complete"

        recent_cutoff = timezone.now() - timedelta(hours=24)

        if self.updated_at and self.updated_at >= recent_cutoff:
            return "operating"

        return "progress"

    @property
    def display_status_label(self):
        labels = {
            "operating": "Currently Operating",
            "progress": "In Progress",
            "complete": "Adventure Complete",
        }
        return labels[self.display_status_key]

    @property
    def is_currently_operating(self):
        return self.display_status_key == "operating"

    def get_absolute_url(self):
        return reverse("adventure_detail", kwargs={"slug": self.slug})

    def __str__(self):
        return self.title


class JournalEntry(models.Model):
    adventure = models.ForeignKey(Adventure, on_delete=models.CASCADE, related_name="journal_entries")
    title = models.CharField(max_length=180, blank=True)
    body = models.TextField()
    entry_at = models.DateTimeField(default=timezone.now)
    is_public = models.BooleanField(default=True, help_text="Visible to everyone who can view this Adventure.")
    radio = models.CharField(max_length=150, blank=True)
    antenna = models.CharField(max_length=150, blank=True)
    equipment_description = models.TextField(blank=True)
    qrp = models.BooleanField(default=False)
    pota = models.BooleanField(default=False)
    portable = models.BooleanField(default=False)
    mobile = models.BooleanField(default=False)
    sota = models.BooleanField(default=False)
    wwff = models.BooleanField(default=False)
    contest = models.BooleanField(default=False)
    field_day = models.BooleanField(default=False)
    club_event = models.BooleanField(default=False)
    other_method = models.BooleanField(default=False)

    mode_ssb = models.BooleanField(default=False)
    mode_cw = models.BooleanField(default=False)
    mode_digital = models.BooleanField(default=False)
    mode_fm = models.BooleanField(default=False)
    mode_am = models.BooleanField(default=False)
    mode_other = models.BooleanField(default=False)
    # Retained for compatibility with earlier builds; new details belong in Journal Notes.
    other_operating_method = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["entry_at", "created_at"]

    @property
    def contact_count(self):
        return self.contacts.count()

    @property
    def longest_contact(self):
        return (
            self.contacts.exclude(distance_miles__isnull=True)
            .order_by("-distance_miles")
            .first()
        )

    @property
    def contact_country_count(self):
        return (
            self.contacts.exclude(country="")
            .values("country")
            .distinct()
            .count()
        )

    @property
    def contact_state_count(self):
        return (
            self.contacts.exclude(state="")
            .values("state", "country")
            .distinct()
            .count()
        )

    def __str__(self):
        return self.title or f"Journal Entry - {self.entry_at:%Y-%m-%d}"


class JournalContact(models.Model):
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.CASCADE,
        related_name="contacts",
    )
    qso_date = models.DateField()
    time_on = models.TimeField(null=True, blank=True)
    callsign = models.CharField(max_length=32)
    mode = models.CharField(max_length=32, blank=True)
    name = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=80, blank=True)
    country = models.CharField(max_length=120, blank=True)
    distance_miles = models.PositiveIntegerField(null=True, blank=True)
    comment = models.TextField(blank=True)
    grid_square = models.CharField(max_length=12, blank=True)
    fingerprint = models.CharField(max_length=64, db_index=True)
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["qso_date", "time_on", "callsign"]
        constraints = [
            models.UniqueConstraint(
                fields=["journal_entry", "fingerprint"],
                name="unique_contact_per_journal_import",
            )
        ]

    @property
    def location_label(self):
        if self.state and self.country:
            return f"{self.state}, {self.country}"

        return self.state or self.country

    def __str__(self):
        return f"{self.callsign} â€” {self.qso_date}"


class Photo(models.Model):
    class ModerationStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REVIEW = "review", "Needs Review"
        REJECTED = "rejected", "Rejected"

    journal_entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="adventure_photos/%Y/%m/")
    caption = models.CharField(max_length=240, blank=True)
    taken_at = models.DateTimeField(null=True, blank=True)
    display_order = models.PositiveIntegerField(default=0)
    file_hash = models.CharField(max_length=64, blank=True, db_index=True)
    moderation_status = models.CharField(max_length=12, choices=ModerationStatus.choices, default=ModerationStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["taken_at", "display_order", "created_at"]

    def __str__(self):
        return self.caption or f"Photo {self.pk or ''}".strip()


class Comment(models.Model):
    adventure = models.ForeignKey(Adventure, on_delete=models.CASCADE, related_name="comments")
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="adventure_comments")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Comment by {self.operator} on {self.adventure}"


class MemberProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="member_profile")
    callsign = models.CharField(max_length=20, unique=True, blank=True)
    display_name = models.CharField(max_length=120, blank=True)
    bio = models.TextField(blank=True)
    home_city = models.CharField(max_length=100, blank=True)
    home_state = models.CharField(max_length=80, blank=True)
    home_country = models.CharField(max_length=80, default="USA")
    website = models.URLField(blank=True)
    profile_is_public = models.BooleanField(default=True)
    email_visible_to_members = models.BooleanField(
        default=True,
        help_text="Show my email address to signed-in Radio Outdoors Members.",
    )
    callsign_verified = models.BooleanField(default=False)
    qrz_verified_at = models.DateTimeField(null=True, blank=True)
    qrz_first_name = models.CharField(max_length=120, blank=True)
    qrz_last_name = models.CharField(max_length=120, blank=True)
    qrz_city = models.CharField(max_length=120, blank=True)
    qrz_state = models.CharField(max_length=100, blank=True)
    qrz_country = models.CharField(max_length=120, blank=True)
    qrz_grid = models.CharField(max_length=12, blank=True)
    qrz_license_class = models.CharField(max_length=30, blank=True)
    qrz_expiration = models.CharField(max_length=20, blank=True)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="verified_member_profiles")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["callsign"]

    def save(self, *args, **kwargs):
        self.callsign = self.callsign.strip().upper()
        super().save(*args, **kwargs)

    @property
    def public_name(self):
        return self.display_name or self.user.get_full_name() or self.user.username

    @property
    def home_label(self):
        return ", ".join(x for x in [self.home_city, self.home_state, self.home_country] if x)

    def __str__(self):
        return self.callsign or self.user.username

class MemberCallsignAudit(models.Model):
    member = models.ForeignKey(
        "MemberProfile",
        on_delete=models.CASCADE,
        related_name="callsign_audits",
    )
    old_callsign = models.CharField(max_length=20)
    new_callsign = models.CharField(max_length=20)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at"]

    def __str__(self):
        return f"{self.old_callsign} to {self.new_callsign}"

class FollowRelationship(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        DECLINED = "declined", "Declined"
        BLOCKED = "blocked", "Blocked"

    member = models.ForeignKey(
        "MemberProfile",
        on_delete=models.CASCADE,
        related_name="followers",
    )
    follower = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="member_following",
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["member", "follower"],
                name="unique_member_follower_relationship",
            )
        ]

    def __str__(self):
        return f"{self.follower} follows {self.member}: {self.status}"

class FollowerInvitation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Invitation Sent"
        ACCEPTED = "accepted", "Accepted"
        CANCELLED = "cancelled", "Cancelled"

    member = models.ForeignKey(
        "MemberProfile",
        on_delete=models.CASCADE,
        related_name="follower_invitations",
    )
    name = models.CharField(max_length=150)
    email = models.EmailField()
    token = models.CharField(max_length=64, unique=True)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
    )
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accepted_follower_invitations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["member", "email"],
                name="unique_follower_invitation_per_member_email",
            )
        ]

    def ensure_token(self):
        import secrets
        if not self.token:
            self.token = secrets.token_urlsafe(32)

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        self.ensure_token()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.email} invited by {self.member}"


class BlockedDomain(models.Model):
    domain = models.CharField(max_length=255, unique=True)
    reason = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["domain"]

    def save(self, *args, **kwargs):
        self.domain = self.domain.strip().lower().lstrip("@")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.domain
