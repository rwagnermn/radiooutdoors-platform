from io import BytesIO
from pathlib import Path

from django.core.files.base import ContentFile
from PIL import Image, ImageOps


MAX_PROFILE_PHOTO_BYTES = 12 * 1024 * 1024
MAX_PROFILE_PHOTO_DIMENSION = 1200
PROFILE_PHOTO_QUALITY = 85
MAX_LOCATION_PHOTO_DIMENSION = 1600


def optimize_profile_photo(uploaded_file):
    """Return a web-sized JPEG without relying on local filesystem paths."""
    uploaded_file.seek(0)
    with Image.open(uploaded_file) as source:
        image = ImageOps.exif_transpose(source)
        image.seek(0)
        image.thumbnail(
            (MAX_PROFILE_PHOTO_DIMENSION, MAX_PROFILE_PHOTO_DIMENSION),
            Image.Resampling.LANCZOS,
        )

        if image.mode in {"RGBA", "LA"} or (
            image.mode == "P" and "transparency" in image.info
        ):
            rgba = image.convert("RGBA")
            flattened = Image.new("RGB", rgba.size, "white")
            flattened.paste(rgba, mask=rgba.getchannel("A"))
            image = flattened
        else:
            image = image.convert("RGB")

        output = BytesIO()
        image.save(
            output,
            format="JPEG",
            quality=PROFILE_PHOTO_QUALITY,
            optimize=True,
            progressive=True,
        )

    stem = Path(uploaded_file.name).stem or "profile-photo"
    return ContentFile(output.getvalue(), name=f"{stem}.jpg")


def optimize_location_photo(uploaded_file):
    """Return an aspect-preserving, web-sized Location JPEG."""
    uploaded_file.seek(0)
    with Image.open(uploaded_file) as source:
        image = ImageOps.exif_transpose(source)
        image.thumbnail(
            (MAX_LOCATION_PHOTO_DIMENSION, MAX_LOCATION_PHOTO_DIMENSION),
            Image.Resampling.LANCZOS,
        )
        if image.mode in {"RGBA", "LA"} or (
            image.mode == "P" and "transparency" in image.info
        ):
            rgba = image.convert("RGBA")
            flattened = Image.new("RGB", rgba.size, "white")
            flattened.paste(rgba, mask=rgba.getchannel("A"))
            image = flattened
        else:
            image = image.convert("RGB")
        output = BytesIO()
        image.save(
            output,
            format="JPEG",
            quality=PROFILE_PHOTO_QUALITY,
            optimize=True,
            progressive=True,
        )
    stem = Path(uploaded_file.name).stem or "location-photo"
    return ContentFile(output.getvalue(), name=f"{stem}.jpg")
