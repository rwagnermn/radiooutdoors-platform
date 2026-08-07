from django import forms
from django.core.files.uploadedfile import UploadedFile
from PIL import Image, UnidentifiedImageError

from .models import MemberProfile
from .profile_images import MAX_PROFILE_PHOTO_BYTES, optimize_profile_photo


class MemberProfileForm(forms.ModelForm):
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)
    remove_profile_photo = forms.BooleanField(
        required=False,
        widget=forms.HiddenInput(),
    )

    class Meta:
        model = MemberProfile
        fields = [
            "profile_photo",
            "display_name",
            "bio",
            "home_city",
            "home_state",
            "home_country",
            "website",
            "profile_is_public",
            "email_visible_to_members",
        ]
        widgets = {
            "profile_photo": forms.FileInput(
                attrs={"accept": "image/jpeg,image/png,image/gif,image/webp"}
            ),
            "bio": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if user:
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name
            self.fields["email"].initial = user.email
        self._original_photo_name = (
            self.instance.profile_photo.name
            if self.instance and self.instance.profile_photo
            else ""
        )

    def clean_profile_photo(self):
        photo = self.cleaned_data.get("profile_photo")
        if not photo or photo is False or not isinstance(photo, UploadedFile):
            return photo
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
        return optimize_profile_photo(photo)

    def save(self, commit=True):
        old_photo_name = self._original_photo_name
        profile = super().save(commit=False)
        if self.cleaned_data.get("remove_profile_photo"):
            profile.profile_photo = ""
        if self.user:
            self.user.first_name = self.cleaned_data["first_name"].strip()
            self.user.last_name = self.cleaned_data["last_name"].strip()
            self.user.email = self.cleaned_data["email"].strip()
            if commit:
                self.user.save(update_fields=["first_name", "last_name", "email"])
        if commit:
            profile.save()
            new_photo_name = profile.profile_photo.name if profile.profile_photo else ""
            if old_photo_name and old_photo_name != new_photo_name:
                profile.profile_photo.storage.delete(old_photo_name)
        return profile


class MemberDeleteForm(forms.Form):
    callsign = forms.CharField(
        label="Type the callsign to confirm deletion",
        max_length=20,
    )

    def __init__(self, *args, expected_callsign="", **kwargs):
        self.expected_callsign = expected_callsign.upper()
        super().__init__(*args, **kwargs)

    def clean_callsign(self):
        value = self.cleaned_data["callsign"].strip().upper()
        if value != self.expected_callsign:
            raise forms.ValidationError("The callsign does not match.")
        return value
