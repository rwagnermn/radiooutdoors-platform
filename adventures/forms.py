from django import forms
from django.core.files.uploadedfile import UploadedFile
from django.db.models import Q
from django.db.models.functions import Lower
from PIL import Image, UnidentifiedImageError

from core.models import Adventure, Comment, JournalContact, JournalEntry, Location, LocationType as LocationTypeRecord, OperatingLocation
from core.profile_images import MAX_PROFILE_PHOTO_BYTES, optimize_location_photo
from core.photo_moderation import validate_image_file
from core.location_privacy import visible_locations


class AdventureLocationChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        prefix = "Private — " if obj.visibility == Location.Visibility.PRIVATE else ""
        return f"{prefix}{obj.name}"


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        single_clean = super().clean
        files = data if isinstance(data, (list, tuple)) else [data]
        cleaned = []
        for item in files:
            image = single_clean(item, initial)
            if image and image.size > MAX_PROFILE_PHOTO_BYTES:
                raise forms.ValidationError("Each image must be smaller than 12 MB.")
            if image:
                validate_image_file(image)
                cleaned.append(optimize_location_photo(image))
        return cleaned if isinstance(data, (list, tuple)) else (cleaned[0] if cleaned else None)


class AdventureForm(forms.ModelForm):
    photos = MultipleImageField(
        required=False,
        help_text="Select or paste one or more images.",
    )
    class Meta:
        model = Adventure
        fields = [
            "title",
            "is_public",
            "operating_callsign",
            "operating_callsign_type",
            "operating_identity_name",
            "operating_callsign_explanation",
            "operating_callsign_url",
            "operating_start_date",
            "operating_end_date",
        ]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "placeholder": "Adventure - today's date",
                    "autocomplete": "off",
                }
            ),
            "operating_callsign": forms.TextInput(
                attrs={"autocapitalize": "characters", "autocomplete": "off"}
            ),
            "operating_callsign_explanation": forms.Textarea(attrs={"rows": 3}),
            "operating_start_date": forms.DateInput(attrs={"type": "date"}),
            "operating_end_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.fields["operating_callsign"].required = True
        self.fields["operating_callsign_type"].required = True

        if not self.is_bound and not self.instance.pk:
            self.initial.setdefault("is_public", True)
            if user:
                profile = getattr(user, "member_profile", None)
                self.initial.setdefault(
                    "operating_callsign",
                    profile.callsign if profile and profile.callsign else user.username,
                )

    def clean_operating_callsign(self):
        callsign = self.cleaned_data["operating_callsign"].strip().upper()
        if not callsign:
            raise forms.ValidationError("Enter the callsign used for this Adventure.")
        return callsign

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("operating_start_date")
        end = cleaned.get("operating_end_date")
        if start and end and end < start:
            self.add_error("operating_end_date", "End date cannot be before start date.")
        return cleaned

class LocationForm(forms.ModelForm):
    remove_location_photo = forms.BooleanField(
        required=False,
        widget=forms.HiddenInput(),
    )

    def __init__(self, *args, **kwargs):
        self.require_coordinates = kwargs.pop("require_coordinates", False)
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self._original_photo_name = (
            self.instance.photo.name
            if self.instance and self.instance.photo
            else ""
        )
        available_types = LocationTypeRecord.objects.filter(is_active=True)
        current_key = self.instance.location_type if self.instance and self.instance.pk else ""
        if current_key:
            available_types = LocationTypeRecord.objects.filter(
                Q(is_active=True) | Q(key=current_key)
            )
        self.fields["location_type"].choices = [
            (item.key, item.name + (" (Inactive)" if not item.is_active else ""))
            for item in available_types.order_by(Lower("name"))
        ]

    def clean_location_type(self):
        key = self.cleaned_data["location_type"]
        location_type = LocationTypeRecord.objects.filter(key=key).first()
        if location_type is None:
            raise forms.ValidationError("Choose a valid Location Type.")
        current_key = self.instance.location_type if self.instance and self.instance.pk else ""
        if not location_type.is_active and key != current_key:
            raise forms.ValidationError("Choose an active Location Type.")
        self._selected_location_type_record = location_type
        return key

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if not photo or photo is False or not isinstance(photo, UploadedFile):
            return photo
        validate_image_file(photo)
        if photo.size > MAX_PROFILE_PHOTO_BYTES:
            raise forms.ValidationError("Choose an image smaller than 12 MB.")
        try:
            photo.seek(0)
            with Image.open(photo) as image:
                image.verify()
            photo.seek(0)
        except (
            Image.DecompressionBombError,
            UnidentifiedImageError,
            OSError,
            ValueError,
        ):
            raise forms.ValidationError(
                "Choose a valid JPEG, PNG, GIF, or WebP image."
            )
        return optimize_location_photo(photo)

    def clean(self):
        cleaned = super().clean()
        latitude = cleaned.get("latitude")
        longitude = cleaned.get("longitude")
        if self.require_coordinates and (latitude is None or longitude is None):
            raise forms.ValidationError(
                "Place the Location pin before continuing."
            )
        if cleaned.get("has_operating_advisory") and not cleaned.get("operating_advisory", "").strip():
            self.add_error(
                "operating_advisory",
                "Add a short note explaining the Operating Advisory.",
            )
        if (
            self.instance.pk
            and self.instance.visibility == Location.Visibility.PUBLIC
            and cleaned.get("visibility") == Location.Visibility.PRIVATE
            and self.user
            and not self.user.is_staff
            and self.instance.adventures.exclude(owner=self.user).exists()
        ):
            self.add_error(
                "visibility",
                "This Location is used by Adventures belonging to other members. "
                "Contact Radio Outdoors staff before changing it to Private.",
            )
        return cleaned

    def save(self, commit=True):
        old_photo_name = self._original_photo_name
        location = super().save(commit=False)
        if self.files.get(self.add_prefix("photo")):
            location.photo_moderation_status = "pending"
            location.photo_moderation_reason = ""
            location.photo_moderation_categories = []
            location.photo_moderation_confidence = None
            location.photo_moderation_provider = ""
            location.photo_moderation_provider_model = ""
            location.photo_automated_decision = ""
            location.photo_rejection_reason_code = ""
            location.photo_rejection_explanation = ""
        location.location_type_record = self._selected_location_type_record
        if self.cleaned_data.get("remove_location_photo"):
            location.photo = ""
        if commit:
            location.save()
            new_photo_name = location.photo.name if location.photo else ""
            if old_photo_name and old_photo_name != new_photo_name:
                location.photo.storage.delete(old_photo_name)
        return location

    class Meta:
        model = Location
        fields = [
            "name",
            "visibility",
            "location_type",
            "street_address",
            "address_line_2",
            "city",
            "state",
            "postal_code",
            "country",
            "latitude",
            "longitude",
            "official_website",
            "reference_code",
            "description",
            "parking",
            "restrooms",
            "picnic_tables",
            "shelter",
            "shade",
            "power",
            "drinking_water",
            "cell_coverage_bars",
            "ambient_noise_level",
            "photo",
            "has_operating_advisory",
            "operating_advisory",
        ]
        widgets = {
            "visibility": forms.RadioSelect(),
            "photo": forms.FileInput(
                attrs={"accept": "image/jpeg,image/png,image/gif,image/webp"}
            ),
            "street_address": forms.TextInput(
                attrs={
                    "placeholder": "Street address",
                    "autocomplete": "street-address",
                }
            ),
            "address_line_2": forms.TextInput(
                attrs={
                    "placeholder": "Address line 2, entrance, or unit",
                    "autocomplete": "address-line2",
                }
            ),
            "city": forms.TextInput(
                attrs={
                    "placeholder": "City",
                    "autocomplete": "address-level2",
                }
            ),
            "state": forms.TextInput(
                attrs={
                    "placeholder": "State or province",
                    "autocomplete": "address-level1",
                }
            ),
            "postal_code": forms.TextInput(
                attrs={
                    "placeholder": "ZIP or postal code",
                    "autocomplete": "postal-code",
                }
            ),
            "country": forms.TextInput(
                attrs={
                    "placeholder": "Country",
                    "autocomplete": "country-name",
                }
            ),
            "latitude": forms.HiddenInput(),
            "longitude": forms.HiddenInput(),
            "official_website": forms.URLInput(
                attrs={
                    "placeholder": "https://...",
                    "autocomplete": "url",
                }
            ),
            "reference_code": forms.TextInput(
                attrs={
                    "placeholder": "Example: US-2524, KFF-2524, airport ID",
                    "autocomplete": "off",
                }
            ),
            "description": forms.Textarea(attrs={"rows": 4}),
            "operating_advisory": forms.Textarea(attrs={"rows": 4, "placeholder": "Example: Airport manager does not permit portable operation near the hangars."}),
        }


class OperatingLocationForm(forms.ModelForm):
    AMENITY_DEFAULTS = {
        "parking": OperatingLocation.UnknownYesNo.UNKNOWN,
        "restrooms": OperatingLocation.UnknownYesNo.UNKNOWN,
        "picnic_tables": OperatingLocation.UnknownYesNo.UNKNOWN,
        "shelter": OperatingLocation.UnknownYesNo.UNKNOWN,
        "shade": OperatingLocation.UnknownYesNo.UNKNOWN,
        "power": OperatingLocation.UnknownYesNo.UNKNOWN,
        "drinking_water": OperatingLocation.UnknownYesNo.UNKNOWN,
        "cell_coverage_bars": OperatingLocation.CellBars.UNKNOWN,
        "ambient_noise_level": OperatingLocation.AmbientNoise.UNKNOWN,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, default in self.AMENITY_DEFAULTS.items():
            self.fields[field_name].required = False
            if not self.is_bound and not self.instance.pk:
                self.initial.setdefault(field_name, default)

    def clean(self):
        cleaned = super().clean()
        for field_name, default in self.AMENITY_DEFAULTS.items():
            if cleaned.get(field_name) in (None, ""):
                cleaned[field_name] = default
        if cleaned.get("latitude") is None or cleaned.get("longitude") is None:
            raise forms.ValidationError(
                "Place the Operating Position pin before continuing."
            )
        return cleaned

    class Meta:
        model = OperatingLocation
        fields = [
            "name",
            "description",
            "parking",
            "restrooms",
            "picnic_tables",
            "shelter",
            "shade",
            "power",
            "drinking_water",
            "cell_coverage_bars",
            "ambient_noise_level",
            "latitude",
            "longitude",
            "parking",
            "restrooms",
            "picnic_tables",
            "shelter",
            "shade",
            "power",
            "drinking_water",
            "cell_coverage_bars",
            "ambient_noise_level",
        ]
        labels = {
            "name": "Operating Position",
            "description": "Notes (optional)",
            "cell_coverage_bars": "Cell Coverage",
            "ambient_noise_level": "Ambient Noise",
        }
        widgets = {
            "name": forms.TextInput(
                attrs={"placeholder": "Example: Behind the main hangar"}
            ),
            "description": forms.Textarea(attrs={"rows": 4}),
            "latitude": forms.HiddenInput(),
            "longitude": forms.HiddenInput(),
        }


class JournalEntryForm(forms.ModelForm):
    location_name = forms.CharField(
        required=True, max_length=150, label="Location",
        widget=forms.TextInput(attrs={"autocomplete": "off", "placeholder": "Start typing a Location name"}),
        help_text="Start typing to find a Location. Choose a match, or keep what you typed and place the pin manually.",
    )
    location = AdventureLocationChoiceField(
        queryset=Location.objects.none(), required=False,
        widget=forms.HiddenInput,
    )
    location_source = forms.CharField(required=False, widget=forms.HiddenInput)
    google_formatted_address = forms.CharField(required=False, widget=forms.HiddenInput)
    google_city = forms.CharField(required=False, widget=forms.HiddenInput)
    google_state = forms.CharField(required=False, widget=forms.HiddenInput)
    google_country = forms.CharField(required=False, widget=forms.HiddenInput)
    google_location_type = forms.CharField(required=False, widget=forms.HiddenInput)
    photos = MultipleImageField(
        required=False,
        help_text="Select one or more JPG, PNG, WEBP, or HEIC images.",
    )

    class Meta:
        model = JournalEntry
        fields = [
            "entry_at",
            "status",
            "is_public",
            "location",
            "latitude",
            "longitude",
            "operating_callsign",
            "title",
            "body",
            "radio",
            "antenna",
        ]
        labels = {
            "entry_at": "When did this happen?",
            "status": "Journal Status",
            "location": "Location",
            "is_public": "Visible to Everyone",
            "operating_callsign": "Operating Callsign",
            "title": "Journal title (optional)",
            "body": "Tell the story",
            "radio": "Radio (optional)",
            "antenna": "Antenna (optional)",
        }
        widgets = {
            "entry_at": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local",
                    "step": "60",
                },
                format="%Y-%m-%dT%H:%M",
            ),
            "title": forms.TextInput(
                attrs={"placeholder": "Optional title", "autocomplete": "off"}
            ),
            "latitude": forms.HiddenInput(),
            "longitude": forms.HiddenInput(),
            "body": forms.Textarea(
                attrs={
                    "rows": 10,
                    "placeholder": "What do you want to remember about this part of the adventure?",
                }
            ),
        }



    def __init__(self, *args, **kwargs):
        adventure = kwargs.pop("adventure", None)
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.fields["location"].queryset = visible_locations(user).order_by("name")
        self.fields["operating_callsign"].required = True
        if not self.is_bound and not self.instance.pk:
            self.initial.setdefault("is_public", True)
            self.initial.setdefault("status", JournalEntry.Status.OPEN)
            if adventure:
                self.initial.setdefault("location", adventure.location_id)
                if adventure.location_id:
                    self.initial.setdefault("location_name", adventure.location.name)
                if adventure.location_id:
                    self.initial.setdefault("latitude", adventure.location.latitude)
                    self.initial.setdefault("longitude", adventure.location.longitude)
            if adventure:
                self.initial.setdefault(
                    "operating_callsign", adventure.operating_callsign
                )
        self.fields["entry_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["body"].required = True
        self.fields["body"].help_text = (
            "The story is the only required content. One sentence is enough."
        )
        self.fields["radio"].required = False
        self.fields["antenna"].required = False
        if self.instance and self.instance.pk and self.instance.entry_at:
            if self.instance.location_id:
                self.initial.setdefault("location_name", self.instance.location.name)
                self.initial.setdefault("location", self.instance.location_id)
            self.initial["entry_at"] = self.instance.entry_at.strftime(
                "%Y-%m-%dT%H:%M"
            )

    def clean_operating_callsign(self):
        callsign = self.cleaned_data["operating_callsign"].strip().upper()
        if not callsign:
            raise forms.ValidationError("Enter the callsign used for this Journal entry.")
        return callsign

    def clean(self):
        cleaned = super().clean()
        name = (cleaned.get("location_name") or "").strip()
        if not name:
            self.add_error("location_name", "Enter a Location name.")
        location = cleaned.get("location")
        if location and name.casefold() != location.name.casefold():
            cleaned["location"] = None
            location = None
        latitude, longitude = cleaned.get("latitude"), cleaned.get("longitude")
        if location:
            if latitude is None:
                latitude = location.latitude
                cleaned["latitude"] = latitude
            if longitude is None:
                longitude = location.longitude
                cleaned["longitude"] = longitude
        if latitude is None or longitude is None:
            self.add_error("latitude", "Place the Journal operating-position pin on the map.")
        elif not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            self.add_error("latitude", "Enter valid map coordinates.")
        return cleaned

    def resolve_location(self, user):
        if self.cleaned_data.get("location"):
            return self.cleaned_data.get("location")
        source = self.cleaned_data.get("location_source")
        type_mapping = {
            "park": Location.LocationType.PARK, "campground": Location.LocationType.CAMPGROUND,
            "airport": Location.LocationType.AIRPORT, "natural_feature": Location.LocationType.OTHER,
        }
        return Location.objects.create(
            name=self.cleaned_data["location_name"].strip(),
            created_by=user,
            visibility=Location.Visibility.PUBLIC,
            location_type=type_mapping.get(self.cleaned_data.get("google_location_type"), Location.LocationType.OTHER),
            street_address=(self.cleaned_data.get("google_formatted_address") or "").strip() if source == "google" else "",
            city=(self.cleaned_data.get("google_city") or "").strip(),
            state=(self.cleaned_data.get("google_state") or "").strip(),
            country=(self.cleaned_data.get("google_country") or "USA").strip(),
            latitude=self.cleaned_data["latitude"],
            longitude=self.cleaned_data["longitude"],
        )


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ["body"]
        widgets = {
            "body": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Add a comment about this adventure...",
                }
            ),
        }
        labels = {
            "body": "Comment",
        }


class JournalContactForm(forms.ModelForm):
    class Meta:
        model = JournalContact
        fields = ["qso_date", "time_on", "callsign", "band", "mode", "frequency", "signal_report", "comment", "pota_park_reference", "pota_park_name"]
        labels = {
            "qso_date": "Date", "time_on": "Time", "callsign": "Worked callsign",
            "comment": "Notes", "pota_park_reference": "POTA park reference",
            "pota_park_name": "POTA park name",
        }
        widgets = {
            "qso_date": forms.DateInput(attrs={"type": "date"}),
            "time_on": forms.TimeInput(attrs={"type": "time"}),
            "comment": forms.Textarea(attrs={"rows": 4}),
        }

    def clean_callsign(self):
        return self.cleaned_data["callsign"].strip().upper()

    def clean_pota_park_reference(self):
        return self.cleaned_data["pota_park_reference"].strip().upper()


class AdifImportForm(forms.Form):
    adif_file = forms.FileField(
        label="ADIF File",
        help_text=(
            "Select a QRZ, LoTW, WSJT-X, N3FJP, HAMRS, "
            "or other ADIF export."
        ),
        widget=forms.ClearableFileInput(
            attrs={"accept": ".adi,.adif"}
        ),
    )

    def clean_adif_file(self):
        uploaded_file = self.cleaned_data["adif_file"]
        filename = uploaded_file.name.lower()

        if not filename.endswith((".adi", ".adif")):
            raise forms.ValidationError(
                "Please select a file ending in .adi or .adif."
            )

        if uploaded_file.size > 25 * 1024 * 1024:
            raise forms.ValidationError(
                "ADIF files must be 25 MB or smaller."
            )

        return uploaded_file
