from django import forms
from django.core.files.uploadedfile import UploadedFile
from PIL import Image, UnidentifiedImageError

from .models import DefaultLocationImage
from .profile_images import MAX_PROFILE_PHOTO_BYTES, optimize_location_photo


class DefaultLocationImageForm(forms.ModelForm):
    class Meta:
        model = DefaultLocationImage
        fields = [
            "image",
            "source_title",
            "source_url",
            "creator",
            "license_name",
            "license_url",
            "displayed_credit",
            "active",
        ]
        widgets = {
            "image": forms.FileInput(
                attrs={"accept": "image/jpeg,image/png,image/gif,image/webp"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_image_name = self.instance.image.name if self.instance.image else ""

    def clean_image(self):
        image_file = self.cleaned_data.get("image")
        if not image_file or not isinstance(image_file, UploadedFile):
            return image_file
        if image_file.size > MAX_PROFILE_PHOTO_BYTES:
            raise forms.ValidationError("Choose an image smaller than 12 MB.")
        try:
            image_file.seek(0)
            with Image.open(image_file) as image:
                image.verify()
            image_file.seek(0)
        except (
            Image.DecompressionBombError,
            UnidentifiedImageError,
            OSError,
            ValueError,
        ):
            raise forms.ValidationError(
                "Choose a valid JPEG, PNG, GIF, or WebP image."
            )
        return optimize_location_photo(image_file)

    def save(self, commit=True):
        old_name = self._original_image_name
        default_image = super().save(commit=commit)
        if commit:
            new_name = default_image.image.name if default_image.image else ""
            if old_name and old_name != new_name:
                default_image.image.storage.delete(old_name)
        return default_image
