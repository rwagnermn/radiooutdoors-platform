from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.functional import cached_property
from django.db.models.functions import Lower


class LocationType(models.Model):
    key = models.SlugField(max_length=30, unique=True, editable=False)
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = [Lower("name")]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                name="core_location_type_name_ci_unique",
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = " ".join(self.name.split())
        if not self.key:
            base = (slugify(self.name) or "location-type")[:30]
            candidate = base
            counter = 2
            while LocationType.objects.filter(key=candidate).exclude(pk=self.pk).exists():
                suffix = f"-{counter}"
                candidate = f"{base[:30-len(suffix)]}{suffix}"
                counter += 1
            self.key = candidate
        super().save(*args, **kwargs)


class Location(models.Model):
    class Visibility(models.TextChoices):
        PUBLIC = "public", "Public"
        PRIVATE = "private", "Private"

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
        AIRPORT = "airport", "Airport"
        WMA_DNR = "wma_dnr", "WMA / DNR Wildlife Management Land"
        OTHER = "other", "Other"

    name = models.CharField(max_length=150)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_locations",
    )
    visibility = models.CharField(
        max_length=10,
        choices=Visibility.choices,
        default=Visibility.PUBLIC,
        db_index=True,
    )
    slug = models.SlugField(max_length=180, unique=True, blank=True)
    location_type = models.CharField(max_length=30, choices=LocationType.choices, default=LocationType.OTHER)
    location_type_record = models.ForeignKey(
        "core.LocationType",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="locations",
    )
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
    needs_pin_review = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Imported historical Location is waiting for a general map pin.",
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
    parking = models.CharField(max_length=10, choices=[("unknown", "Unknown"), ("yes", "Yes"), ("no", "No")], default="unknown")
    restrooms = models.CharField(max_length=10, choices=[("unknown", "Unknown"), ("yes", "Yes"), ("no", "No")], default="unknown")
    picnic_tables = models.CharField(max_length=10, choices=[("unknown", "Unknown"), ("yes", "Yes"), ("no", "No")], default="unknown")
    shelter = models.CharField(max_length=10, choices=[("unknown", "Unknown"), ("yes", "Yes"), ("no", "No")], default="unknown")
    shade = models.CharField(max_length=10, choices=[("unknown", "Unknown"), ("yes", "Yes"), ("no", "No")], default="unknown")
    power = models.CharField(max_length=10, choices=[("unknown", "Unknown"), ("yes", "Yes"), ("no", "No")], default="unknown")
    drinking_water = models.CharField(max_length=10, choices=[("unknown", "Unknown"), ("yes", "Yes"), ("no", "No")], default="unknown")
    cell_coverage_bars = models.PositiveSmallIntegerField(choices=[(0, "Unknown"), (1, "1 Bar"), (2, "2 Bars"), (3, "3 Bars"), (4, "4 Bars"), (5, "5 Bars")], default=0)
    ambient_noise_level = models.CharField(max_length=20, choices=[("unknown", "Unknown"), ("very_quiet", "Very Quiet"), ("quiet", "Quiet"), ("moderate", "Moderate"), ("busy", "Busy"), ("very_busy", "Very Busy")], default="unknown")
    photo = models.ImageField(
        upload_to="location_photos/%Y/%m/",
        blank=True,
    )
    photo_moderation_status = models.CharField(
        max_length=12,
        choices=[
            ("pending", "Pending Scan"),
            ("approved", "Approved"),
            ("review", "Needs Administrator Review"),
            ("rejected", "Rejected"),
        ],
        default="pending",
        db_index=True,
    )
    photo_moderation_reason = models.CharField(max_length=240, blank=True)
    photo_moderation_categories = models.JSONField(default=list, blank=True)
    photo_moderation_confidence = models.FloatField(null=True, blank=True)
    photo_moderation_provider = models.CharField(max_length=80, blank=True)
    photo_moderation_provider_model = models.CharField(max_length=80, blank=True)
    photo_automated_decision = models.CharField(max_length=32, blank=True)
    photo_rejection_reason_code = models.CharField(max_length=48, blank=True)
    photo_rejection_explanation = models.CharField(max_length=240, blank=True)
    photo_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="reviewed_location_photos",
    )
    photo_reviewed_at = models.DateTimeField(null=True, blank=True)
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

    @property
    def is_private(self):
        return self.visibility == self.Visibility.PRIVATE

    def get_location_type_display(self):
        if self.location_type_record_id:
            return self.location_type_record.name
        return dict(self.LocationType.choices).get(
            self.location_type,
            self.location_type.replace("_", " ").title(),
        )

    @cached_property
    def default_photo_info(self):
        from .location_default_images import default_image_for_location

        return default_image_for_location(self)

    @property
    def display_photo_url(self):
        if self.photo and self.photo_moderation_status == "approved":
            return self.photo.url
        if self.default_photo_info:
            return self.default_photo_info["url"]
        return ""

    @property
    def uses_default_photo(self):
        return not self.photo and bool(self.default_photo_info)


class DefaultLocationImage(models.Model):
    class Key(models.TextChoices):
        PARK = "park", "Park / General Outdoor Site"
        CAMPGROUND = "campground", "Campground / Cabin"
        WILDLIFE = "wildlife", "WMA / Wildlife Area"
        AIRPORT = "airport", "Airport / Aviation Site"
        BOAT_LAUNCH = "boat_launch", "Boat Launch / Marina"
        SCENIC = "scenic", "Scenic Overlook / Other"

    key = models.CharField(max_length=30, choices=Key.choices, unique=True)
    image = models.ImageField(upload_to="location_defaults/", blank=True)
    moderation_status = models.CharField(
        max_length=12,
        choices=[("pending", "Pending Scan"), ("approved", "Approved"), ("review", "Needs Administrator Review"), ("rejected", "Rejected")],
        default="pending",
        db_index=True,
    )
    moderation_reason = models.CharField(max_length=240, blank=True)
    moderation_categories = models.JSONField(default=list, blank=True)
    moderation_confidence = models.FloatField(null=True, blank=True)
    moderation_provider = models.CharField(max_length=80, blank=True)
    moderation_provider_model = models.CharField(max_length=80, blank=True)
    automated_decision = models.CharField(max_length=32, blank=True)
    rejection_reason_code = models.CharField(max_length=48, blank=True)
    rejection_explanation = models.CharField(max_length=240, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_default_location_images")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    source_title = models.CharField(max_length=240)
    source_url = models.URLField()
    creator = models.CharField(max_length=180)
    license_name = models.CharField(max_length=100)
    license_url = models.URLField()
    displayed_credit = models.CharField(max_length=320, blank=True)
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]

    @property
    def credit_text(self):
        return self.displayed_credit or f"{self.source_title} by {self.creator}"

    def __str__(self):
        return self.get_key_display()


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
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_operating_locations",
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    parking = models.CharField(max_length=10, choices=[("unknown", "Unknown"), ("yes", "Yes"), ("no", "No")], default="unknown")
    restrooms = models.CharField(max_length=10, choices=[("unknown", "Unknown"), ("yes", "Yes"), ("no", "No")], default="unknown")
    picnic_tables = models.CharField(max_length=10, choices=[("unknown", "Unknown"), ("yes", "Yes"), ("no", "No")], default="unknown")
    shelter = models.CharField(max_length=10, choices=[("unknown", "Unknown"), ("yes", "Yes"), ("no", "No")], default="unknown")
    shade = models.CharField(max_length=10, choices=[("unknown", "Unknown"), ("yes", "Yes"), ("no", "No")], default="unknown")
    power = models.CharField(max_length=10, choices=[("unknown", "Unknown"), ("yes", "Yes"), ("no", "No")], default="unknown")
    drinking_water = models.CharField(max_length=10, choices=[("unknown", "Unknown"), ("yes", "Yes"), ("no", "No")], default="unknown")
    cell_coverage_bars = models.PositiveSmallIntegerField(choices=[(0, "Unknown"), (1, "1 Bar"), (2, "2 Bars"), (3, "3 Bars"), (4, "4 Bars"), (5, "5 Bars")], default=0)
    ambient_noise_level = models.CharField(max_length=20, choices=[("unknown", "Unknown"), ("very_quiet", "Very Quiet"), ("quiet", "Quiet"), ("moderate", "Moderate"), ("busy", "Busy"), ("very_busy", "Very Busy")], default="unknown")
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
        ACTIVE = "active", "Open"
        COMPLETED = "completed", "Complete"

    class OperatingCallsignType(models.TextChoices):
        PERSONAL = "personal", "Personal callsign"
        SPECIAL_EVENT = "special_event", "Special Event callsign"
        CLUB = "club", "Club callsign"
        CONTEST = "contest", "Contest callsign"
        PORTABLE_REGIONAL = "portable_regional", "Portable/Regional variation"
        OTHER = "other", "Other authorized callsign"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="adventures")
    title = models.CharField(max_length=180, blank=True)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, related_name="adventures")
    operating_location = models.ForeignKey(OperatingLocation, on_delete=models.SET_NULL, null=True, blank=True, related_name="adventures")
    operating_callsign = models.CharField(max_length=30, blank=True)
    operating_callsign_type = models.CharField(
        max_length=24,
        choices=OperatingCallsignType.choices,
        default=OperatingCallsignType.PERSONAL,
    )
    operating_identity_name = models.CharField(
        "Event or organization name", max_length=180, blank=True
    )
    operating_callsign_explanation = models.TextField(
        "Optional explanation", blank=True
    )
    operating_callsign_url = models.URLField(
        "Optional event website/reference", blank=True
    )
    operating_start_date = models.DateField("Start date", null=True, blank=True)
    operating_end_date = models.DateField("End date", null=True, blank=True)
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
    cover_photo_is_explicit = models.BooleanField(
        default=False,
        help_text="True when an authorized manager explicitly selected the cover.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def save(self, *args, **kwargs):
        self.operating_callsign = self.operating_callsign.strip().upper()
        if not self.operating_callsign and self.owner_id:
            profile = getattr(self.owner, "member_profile", None)
            self.operating_callsign = (
                profile.callsign if profile and profile.callsign else self.owner.username
            ).strip().upper()
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
        return "complete" if self.status == self.Status.COMPLETED else "active"

    @property
    def display_status_label(self):
        return "Complete" if self.status == self.Status.COMPLETED else "Active"

    def get_status_display(self):
        return self.display_status_label

    @property
    def is_currently_operating(self):
        return self.status == self.Status.ACTIVE

    def get_absolute_url(self):
        return reverse("adventure_detail", kwargs={"slug": self.slug})

    def refresh_status_from_journals(self):
        if not self.pk:
            return
        statuses = list(self.journal_entries.filter(is_adventure_photo_collection=False).values_list("status", flat=True))
        new_status = (
            self.Status.COMPLETED
            if statuses and all(value == JournalEntry.Status.COMPLETED for value in statuses)
            else self.Status.ACTIVE
        )
        updates = {"status": new_status, "updated_at": timezone.now()}
        updates["completed_at"] = timezone.now() if new_status == self.Status.COMPLETED else None
        Adventure.objects.filter(pk=self.pk).update(**updates)
        self.status = new_status
        self.completed_at = updates["completed_at"]


    def eligible_cover_photos(self):
        """Approved, public photos for this Adventure in cover-priority order."""
        return Photo.objects.filter(
            journal_entry__adventure=self,
            journal_entry__is_public=True,
            moderation_status=Photo.ModerationStatus.APPROVED,
        ).select_related("journal_entry").order_by(
            "-journal_entry__is_adventure_photo_collection",
            "taken_at",
            "display_order",
            "created_at",
            "pk",
        )

    @property
    def display_cover_photo(self):
        """Resolve the public cover without mutating the stored owner selection."""
        if self.cover_photo_is_explicit and self.cover_photo_id:
            selected = self.eligible_cover_photos().filter(pk=self.cover_photo_id).first()
            if selected:
                return selected
        return self.eligible_cover_photos().first()

    def __str__(self):
        return self.title


class PotaImportBatch(models.Model):
    class Source(models.TextChoices):
        ACTIVATION_HISTORY = "activation_history", "POTA Activation History"
        HUNTER_LOG = "hunter_log", "POTA Hunter Log"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pota_import_batches")
    source = models.CharField(max_length=24, choices=Source.choices, default=Source.ACTIVATION_HISTORY)
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    diagnostics = models.JSONField(default=dict, blank=True)


class PotaCallsignAttestation(models.Model):
    batch = models.ForeignKey(PotaImportBatch, on_delete=models.CASCADE, related_name="callsign_attestations")
    member = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pota_callsign_attestations")
    callsign = models.CharField(max_length=30)
    attestation_text = models.TextField()
    attested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["batch", "callsign"], name="unique_pota_callsign_attestation")]


class PotaActivationImport(models.Model):
    adventure = models.ForeignKey(Adventure, on_delete=models.CASCADE, related_name="pota_imports")
    journal_entry = models.OneToOneField(
        "JournalEntry", on_delete=models.CASCADE, related_name="pota_import",
        null=True, blank=True,
    )
    batch = models.ForeignKey(PotaImportBatch, on_delete=models.PROTECT, related_name="activations")
    activation_date = models.DateField()
    callsign = models.CharField(max_length=30)
    park_reference = models.CharField(max_length=30)
    park_name = models.CharField(max_length=200)
    entity = models.CharField(max_length=120, blank=True)
    cw_contacts = models.PositiveIntegerField(default=0)
    data_contacts = models.PositiveIntegerField(default=0)
    phone_contacts = models.PositiveIntegerField(default=0)
    total_contacts = models.PositiveIntegerField(default=0)
    source = models.CharField(max_length=24, choices=PotaImportBatch.Source.choices, default=PotaImportBatch.Source.ACTIVATION_HISTORY)
    source_metadata = models.JSONField(default=dict, blank=True)
    fingerprint = models.CharField(max_length=64, unique=True)
    location_resolution = models.CharField(max_length=20, choices=[("existing", "Existing Location"), ("unresolved", "Needs Location")])
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-activation_date", "park_reference"]


class PotaTestResetAudit(models.Model):
    staff_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pota_test_reset_audits",
    )
    performed_at = models.DateTimeField(auto_now_add=True)
    database_identifier = models.CharField(max_length=500)
    deleted_counts = models.JSONField(default=dict, blank=True)
    blocked_counts = models.JSONField(default=dict, blank=True)
    backup_path = models.CharField(max_length=500, blank=True)
    succeeded = models.BooleanField(default=False)
    error_category = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ["-performed_at"]


class JournalEntry(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        COMPLETED = "completed", "Complete"

    adventure = models.ForeignKey(Adventure, on_delete=models.CASCADE, related_name="journal_entries")
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, related_name="journal_entries")
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    title = models.CharField(max_length=180, blank=True)
    body = models.TextField()
    entry_at = models.DateTimeField(default=timezone.now)
    is_public = models.BooleanField(default=True, help_text="Visible to everyone who can view this Adventure.")
    is_adventure_photo_collection = models.BooleanField(
        default=False,
        help_text="System collection for photos uploaded directly with an Adventure.",
    )
    operating_callsign = models.CharField(max_length=30, blank=True)
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
    primary_photo = models.ForeignKey(
        "Photo",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="primary_for_journals",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["entry_at", "created_at"]

    def save(self, *args, **kwargs):
        self.operating_callsign = self.operating_callsign.strip().upper()
        if not self.operating_callsign and self.adventure_id:
            self.operating_callsign = self.adventure.operating_callsign
        if self.location_id:
            if self.latitude is None:
                self.latitude = self.location.latitude
            if self.longitude is None:
                self.longitude = self.location.longitude
        super().save(*args, **kwargs)
        self.adventure.refresh_status_from_journals()

    def delete(self, *args, **kwargs):
        adventure = self.adventure
        result = super().delete(*args, **kwargs)
        adventure.refresh_status_from_journals()
        return result

    @property
    def display_status_label(self):
        return "Complete" if self.status == self.Status.COMPLETED else "Active"

    def get_status_display(self):
        return self.display_status_label

    @property
    def display_status_key(self):
        return "complete" if self.status == self.Status.COMPLETED else "active"

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
    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        POTA_HUNTER = "pota_hunter", "POTA Hunter Log"
        ADIF = "adif", "ADIF"
        OTHER = "other", "Other"

    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.CASCADE,
        related_name="contacts",
        null=True,
        blank=True,
    )
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="contacts", null=True, blank=True)
    adventure = models.ForeignKey(Adventure, on_delete=models.CASCADE, related_name="direct_contacts", null=True, blank=True)
    qso_date = models.DateField()
    time_on = models.TimeField(null=True, blank=True)
    callsign = models.CharField(max_length=32)
    station_callsign = models.CharField(max_length=32, blank=True)
    operator_callsign = models.CharField(max_length=32, blank=True)
    band = models.CharField(max_length=24, blank=True)
    frequency = models.DecimalField(
        max_digits=12, decimal_places=6, null=True, blank=True
    )
    mode = models.CharField(max_length=32, blank=True)
    submode = models.CharField(max_length=32, blank=True)
    name = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=80, blank=True)
    country = models.CharField(max_length=120, blank=True)
    distance_miles = models.PositiveIntegerField(null=True, blank=True)
    comment = models.TextField(blank=True)
    signal_report = models.CharField(max_length=20, blank=True)
    source = models.CharField(max_length=24, choices=Source.choices, default=Source.MANUAL, db_index=True)
    pota_park_reference = models.CharField(max_length=30, blank=True, db_index=True)
    pota_park_name = models.CharField(max_length=200, blank=True)
    is_p2p = models.BooleanField(default=False)
    resolved_location = models.ForeignKey(
        Location,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="contacts",
        help_text="Approximate park Location resolved for this Contact.",
    )
    grid_square = models.CharField(max_length=12, blank=True)
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
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

    @property
    def has_no_pin(self):
        return bool(self.pota_park_reference and self.resolved_location_id is None)

    def clean(self):
        super().clean()
        if self.journal_entry_id:
            journal_adventure_id = self.journal_entry.adventure_id
            if self.adventure_id and self.adventure_id != journal_adventure_id:
                raise ValidationError({
                    "adventure": "A Contact's Adventure must match its Journal's Adventure."
                })

    def save(self, *args, **kwargs):
        if self.journal_entry_id:
            owner_was_missing = not self.owner_id
            self.adventure_id = self.journal_entry.adventure_id
            if owner_was_missing:
                self.owner_id = self.journal_entry.adventure.owner_id
            if kwargs.get("update_fields") is not None:
                update_fields = set(kwargs["update_fields"])
                update_fields.add("adventure")
                if owner_was_missing:
                    update_fields.add("owner")
                kwargs["update_fields"] = update_fields
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.callsign} â€” {self.qso_date}"


class Photo(models.Model):
    class ModerationStatus(models.TextChoices):
        PENDING = "pending", "Pending Scan"
        APPROVED = "approved", "Approved"
        REVIEW = "review", "Needs Administrator Review"
        REJECTED = "rejected", "Rejected"

    journal_entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="adventure_photos/%Y/%m/")
    reference_number = models.CharField(
        max_length=20, unique=True, null=True, blank=True, editable=False,
    )
    original_filename = models.CharField(max_length=255, blank=True)
    original_content_type = models.CharField(max_length=100, blank=True)
    moderation_image = models.ImageField(upload_to="photo_derivatives/moderation/", blank=True)
    web_image = models.ImageField(upload_to="photo_derivatives/web/", blank=True)
    thumbnail_image = models.ImageField(upload_to="photo_derivatives/thumbnails/", blank=True)
    derivative_status = models.CharField(
        max_length=12,
        choices=[("pending", "Pending"), ("ready", "Ready"), ("failed", "Failed")],
        default="pending",
    )
    derivative_metadata = models.JSONField(default=dict, blank=True)
    caption = models.CharField(max_length=240, blank=True)
    taken_at = models.DateTimeField(null=True, blank=True)
    display_order = models.PositiveIntegerField(default=0)
    file_hash = models.CharField(max_length=64, blank=True, db_index=True)
    moderation_status = models.CharField(max_length=12, choices=ModerationStatus.choices, default=ModerationStatus.PENDING)
    automated_decision = models.CharField(max_length=32, blank=True)
    moderation_categories = models.JSONField(default=list, blank=True)
    moderation_confidence = models.FloatField(null=True, blank=True)
    moderation_reason = models.CharField(max_length=240, blank=True)
    moderation_provider = models.CharField(max_length=80, blank=True)
    moderation_provider_model = models.CharField(max_length=80, blank=True)
    rejection_reason_code = models.CharField(max_length=48, blank=True)
    rejection_explanation = models.CharField(max_length=240, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_photos",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["taken_at", "display_order", "created_at"]

    def __str__(self):
        return self.caption or f"Photo {self.pk or ''}".strip()

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.pk and not self.reference_number:
            reference = f"RO-PH-{self.pk:06d}"
            type(self).objects.filter(pk=self.pk, reference_number__isnull=True).update(
                reference_number=reference
            )
            self.reference_number = reference

    @property
    def public_image_url(self):
        if (
            self.web_image
            and self.derivative_status == "ready"
            and self.web_image.storage.exists(self.web_image.name)
        ):
            return self.web_image.url
        return self.image.url

    @property
    def public_thumbnail_url(self):
        if (
            self.thumbnail_image
            and self.derivative_status == "ready"
            and self.thumbnail_image.storage.exists(self.thumbnail_image.name)
        ):
            return self.thumbnail_image.url
        return self.public_image_url

    @property
    def display_file_exists(self):
        for image in (self.web_image, self.image):
            if image and image.storage.exists(image.name):
                return True
        return False

    @property
    def original_file_exists(self):
        return bool(self.image and self.image.storage.exists(self.image.name))

    @property
    def is_publicly_visible(self):
        return self.moderation_status == self.ModerationStatus.APPROVED

    @property
    def moderation_display_status(self):
        if self.automated_decision == "scan_failed":
            return "Scan failed"
        return self.get_moderation_status_display()


class PhotoModerationActionAudit(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="photo_moderation_actions",
    )
    action = models.CharField(max_length=16)
    decision_source = models.CharField(max_length=40)
    scope = models.CharField(max_length=32)
    requested_target_ids = models.JSONField(default=list)
    successful_target_ids = models.JSONField(default=list)
    failed_targets = models.JSONField(default=list)
    target_references = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class AdventureCoverSelectionAudit(models.Model):
    adventure = models.ForeignKey(
        Adventure, on_delete=models.CASCADE, related_name="cover_selection_history"
    )
    photo = models.ForeignKey(Photo, null=True, on_delete=models.SET_NULL)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    action = models.CharField(max_length=32, default="selected")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class PolicyAcceptance(models.Model):
    """Append-only history of the exact policy bundle accepted by an account."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="policy_acceptances",
    )
    account_identifier = models.CharField(max_length=254)
    terms_version = models.CharField(max_length=40)
    privacy_version = models.CharField(max_length=40)
    community_version = models.CharField(max_length=40)
    accepted_at = models.DateTimeField(auto_now_add=True)
    registration_path = models.CharField(max_length=40)
    age_attested = models.BooleanField()
    account_status = models.CharField(max_length=20)

    class Meta:
        ordering = ["-accepted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "user", "terms_version", "privacy_version", "community_version"
                ],
                name="unique_policy_bundle_per_user",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("Policy acceptance history is immutable.")
        super().save(*args, **kwargs)


class CoordinateChangeAudit(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="coordinate_changes",
    )
    record_type = models.CharField(max_length=24)
    record_id = models.PositiveBigIntegerField()
    previous_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    previous_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    new_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    new_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    address_updated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class QuarantinedPhoto(models.Model):
    class Kind(models.TextChoices):
        PHOTO = "photo", "Adventure or Journal photo"
        LOCATION = "location", "Location photo"
        PROFILE = "profile", "Member profile photo"
        DEFAULT = "default", "Default Location image"

    original_kind = models.CharField(max_length=16, choices=Kind.choices)
    original_object_id = models.PositiveBigIntegerField()
    original_target = models.CharField(max_length=48, db_index=True)
    association_id = models.PositiveBigIntegerField(null=True, blank=True)
    association_label = models.CharField(max_length=320)
    image = models.FileField(upload_to="photo_quarantine/", max_length=500)
    metadata = models.JSONField(default=dict)
    removal_reason = models.CharField(max_length=48)
    removal_explanation = models.CharField(max_length=240, blank=True)
    removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="quarantined_photos",
    )
    removed_at = models.DateTimeField(auto_now_add=True)
    restored_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="restored_quarantined_photos",
    )
    restored_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-removed_at"]

    @property
    def is_restored(self):
        return self.restored_at is not None


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
    class VerificationMethod(models.TextChoices):
        NONE = "none", "Not Verified"
        QRZ = "qrz", "QRZ Verified"
        MANUAL = "manual", "Manual Verification"
        ADMIN = "admin", "Admin Verified"
        DEVELOPMENT = "development", "Development Only"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="member_profile")
    callsign = models.CharField(max_length=20, unique=True, blank=True)
    profile_photo = models.ImageField(
        upload_to="member_profiles/%Y/%m/",
        blank=True,
    )
    profile_photo_moderation_status = models.CharField(
        max_length=12,
        choices=Photo.ModerationStatus.choices,
        default=Photo.ModerationStatus.PENDING,
        db_index=True,
    )
    profile_photo_moderation_reason = models.CharField(max_length=240, blank=True)
    profile_photo_moderation_categories = models.JSONField(default=list, blank=True)
    profile_photo_moderation_confidence = models.FloatField(null=True, blank=True)
    profile_photo_moderation_provider = models.CharField(max_length=80, blank=True)
    profile_photo_moderation_provider_model = models.CharField(max_length=80, blank=True)
    profile_photo_automated_decision = models.CharField(max_length=32, blank=True)
    profile_photo_rejection_reason_code = models.CharField(max_length=48, blank=True)
    profile_photo_rejection_explanation = models.CharField(max_length=240, blank=True)
    profile_photo_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="reviewed_profile_photos",
    )
    profile_photo_reviewed_at = models.DateTimeField(null=True, blank=True)
    display_name = models.CharField(max_length=120, blank=True)
    bio = models.TextField(blank=True)
    home_city = models.CharField(max_length=100, blank=True)
    home_state = models.CharField(max_length=80, blank=True)
    home_country = models.CharField(max_length=80, default="USA")
    website = models.URLField(blank=True)
    profile_is_public = models.BooleanField(default=True)
    email_visible_to_members = models.BooleanField(
        default=False,
        help_text="Show my email address to signed-in Radio Outdoors Members.",
    )
    mobile_phone = models.CharField(max_length=16, blank=True)
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    callsign_verified = models.BooleanField(default=False)
    verification_method = models.CharField(
        max_length=12,
        choices=VerificationMethod.choices,
        default=VerificationMethod.NONE,
        db_index=True,
    )
    verification_at = models.DateTimeField(null=True, blank=True)
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

    @property
    def public_profile_photo_url(self):
        if self.profile_photo and self.profile_photo_moderation_status == Photo.ModerationStatus.APPROVED:
            return self.profile_photo.url
        return ""

    def save(self, *args, **kwargs):
        self.callsign = self.callsign.strip().upper()
        super().save(*args, **kwargs)

    def has_valid_verification(self, allow_development=False):
        if not self.callsign or not self.callsign_verified:
            return False
        if self.verification_method in {
            self.VerificationMethod.QRZ,
            self.VerificationMethod.MANUAL,
            self.VerificationMethod.ADMIN,
        }:
            return True
        return bool(
            allow_development
            and self.verification_method == self.VerificationMethod.DEVELOPMENT
        )

    @property
    def public_name(self):
        return self.display_name or self.user.get_full_name() or self.user.username

    @property
    def home_label(self):
        return ", ".join(x for x in [self.home_city, self.home_state, self.home_country] if x)

    def __str__(self):
        return self.callsign or self.user.username


class ManualVerificationRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending Review"
        MORE_INFO = "more_info", "More Information Requested"
        REJECTED = "rejected", "Not Approved"
        APPROVED = "approved", "Approved"

    member = models.OneToOneField(
        MemberProfile,
        on_delete=models.CASCADE,
        related_name="manual_verification_request",
    )
    full_name = models.CharField(max_length=160)
    country = models.CharField(max_length=120)
    authority_url = models.URLField(
        verbose_name="Official licensing authority or recognized callbook link"
    )
    explanation = models.TextField(blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    reviewer_message = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_manual_verifications",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "created_at"]

    def __str__(self):
        return f"{self.member.callsign}: {self.get_status_display()}"

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
