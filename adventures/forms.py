from django import forms
from django.core.files.uploadedfile import UploadedFile
from django.db.models import Q
from django.db.models.functions import Lower
from PIL import Image, UnidentifiedImageError

from core.models import Adventure, Comment, JournalEntry, Location, LocationType as LocationTypeRecord, OperatingLocation
from core.profile_images import MAX_PROFILE_PHOTO_BYTES, optimize_location_photo
from core.photo_moderation import validate_image_file


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
    location = forms.ModelChoiceField(
        queryset=Location.objects.all().order_by("name"),
        required=True,
        empty_label="Choose a Location",
        label="Location",
        help_text="Choose an existing Location or add a new one.",
    )

    operating_location = forms.ModelChoiceField(
        queryset=OperatingLocation.objects.none(),
        required=True,
        empty_label="Choose the exact operating position",
        label="Operating Position",
        help_text="Choose the pin showing where you actually set up the station.",
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
            "location",
            "operating_location",
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

        location_id = None

        if self.is_bound:
            location_id = self.data.get("location")
        elif self.instance and self.instance.pk:
            location_id = self.instance.location_id
        elif self.initial.get("location"):
            location = self.initial["location"]
            location_id = getattr(location, "pk", location)

        if location_id:
            self.fields["operating_location"].queryset = (
                OperatingLocation.objects.filter(location_id=location_id)
                .order_by("name")
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
        if cleaned.get("has_operating_advisory") and not cleaned.get("operating_advisory", "").strip():
            self.add_error(
                "operating_advisory",
                "Add a short note explaining the Operating Advisory.",
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
            "photo",
            "has_operating_advisory",
            "operating_advisory",
        ]
        widgets = {
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
        return cleaned

    class Meta:
        model = OperatingLocation
        fields = [
            "name",
            "description",
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
    photos = MultipleImageField(
        required=False,
        help_text="Select one or more JPG, PNG, WEBP, or HEIC images.",
    )

    class Meta:
        model = JournalEntry
        fields = [
            "entry_at",
            "is_public",
            "operating_callsign",
            "title",
            "body",
            "radio",
            "antenna",
        ]
        labels = {
            "entry_at": "When did this happen?",
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
            "body": forms.Textarea(
                attrs={
                    "rows": 10,
                    "placeholder": "What do you want to remember about this part of the adventure?",
                }
            ),
        }



    def __init__(self, *args, **kwargs):
        adventure = kwargs.pop("adventure", None)
        super().__init__(*args, **kwargs)
        self.fields["operating_callsign"].required = True
        if not self.is_bound and not self.instance.pk:
            self.initial.setdefault("is_public", True)
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
            self.initial["entry_at"] = self.instance.entry_at.strftime(
                "%Y-%m-%dT%H:%M"
            )

    def clean_operating_callsign(self):
        callsign = self.cleaned_data["operating_callsign"].strip().upper()
        if not callsign:
            raise forms.ValidationError("Enter the callsign used for this Journal entry.")
        return callsign


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
