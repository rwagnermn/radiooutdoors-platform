"""Safe, repeatable image normalization for moderation and web delivery."""
from dataclasses import dataclass
from io import BytesIO
import warnings

from django.conf import settings
from django.core.exceptions import ValidationError
from PIL import Image, ImageOps, UnidentifiedImageError


MODERATION_LONG_EDGE = 2560
WEB_LONG_EDGE = 2048
THUMBNAIL_LONG_EDGE = 480
JPEG_MIME_TYPE = "image/jpeg"
SUPPORTED_DECODED_FORMATS = {"JPEG", "MPO", "PNG", "WEBP", "GIF", "HEIC", "HEIF"}
HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}


class ImageNormalizationError(ValidationError):
    def __init__(self, category, message):
        self.category = category
        super().__init__(message, code=category)


@dataclass(frozen=True)
class NormalizedPhoto:
    source_format: str
    source_width: int
    source_height: int
    source_mode: str
    exif_orientation: int | None
    moderation_bytes: bytes
    moderation_width: int
    moderation_height: int
    web_bytes: bytes
    web_width: int
    web_height: int
    thumbnail_bytes: bytes
    thumbnail_width: int
    thumbnail_height: int


def _looks_like_heif(header):
    return len(header) >= 12 and header[4:8] == b"ftyp" and header[8:12] in HEIF_BRANDS


def _encode_jpeg(image, long_edge, quality):
    output_image = image.copy()
    output_image.thumbnail((long_edge, long_edge), Image.Resampling.LANCZOS)
    output = BytesIO()
    output_image.save(
        output, "JPEG", quality=quality, optimize=True, progressive=True,
    )
    return output.getvalue(), output_image.width, output_image.height


def normalize_image_bytes(image_bytes):
    """Decode untrusted bytes and return metadata-free RGB JPEG derivatives."""
    if not image_bytes:
        raise ImageNormalizationError("invalid_image", "The file is not a valid image.")
    if len(image_bytes) > getattr(settings, "PHOTO_MAX_PROCESSING_BYTES", 50 * 1024 * 1024):
        raise ImageNormalizationError(
            "image_too_large", "The image is too large to process safely."
        )

    header = image_bytes[:16]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            source = Image.open(BytesIO(image_bytes))
            source_format = (source.format or "").upper()
            if source_format not in SUPPORTED_DECODED_FORMATS:
                raise ImageNormalizationError(
                    "unsupported_image_type", "This image type is not supported."
                )
            if source_format == "GIF" and getattr(source, "n_frames", 1) != 1:
                raise ImageNormalizationError(
                    "animated_image", "Animated images are not supported."
                )
            source_width, source_height = source.size
            if source_width * source_height > getattr(settings, "PHOTO_MAX_PIXELS", 40_000_000):
                raise ImageNormalizationError(
                    "image_too_large", "The image dimensions are too large to process safely."
                )
            source_mode = source.mode
            orientation = source.getexif().get(274)
            source.seek(0)
            source.load()
            oriented = ImageOps.exif_transpose(source)
            if oriented.mode in {"RGBA", "LA"} or (
                oriented.mode == "P" and "transparency" in oriented.info
            ):
                rgba = oriented.convert("RGBA")
                rgb = Image.new("RGB", rgba.size, "white")
                rgb.paste(rgba, mask=rgba.getchannel("A"))
            else:
                rgb = oriented.convert("RGB")
    except ImageNormalizationError:
        raise
    except Image.DecompressionBombWarning as exc:
        raise ImageNormalizationError(
            "image_too_large", "The image dimensions are too large to process safely."
        ) from exc
    except UnidentifiedImageError as exc:
        if _looks_like_heif(header):
            raise ImageNormalizationError(
                "heic_conversion_unavailable",
                "This iPhone photo uses HEIC format. Please export it as JPEG, or enable HEIC conversion support.",
            ) from exc
        raise ImageNormalizationError("invalid_image", "The file is not a valid image.") from exc
    except MemoryError as exc:
        raise ImageNormalizationError(
            "image_too_large", "The image is too large to process safely."
        ) from exc
    except (OSError, SyntaxError, ValueError) as exc:
        raise ImageNormalizationError("damaged_image", "The image is damaged and could not be read.") from exc

    moderation, mod_width, mod_height = _encode_jpeg(rgb, MODERATION_LONG_EDGE, 88)
    web, web_width, web_height = _encode_jpeg(rgb, WEB_LONG_EDGE, 86)
    thumbnail, thumb_width, thumb_height = _encode_jpeg(rgb, THUMBNAIL_LONG_EDGE, 82)
    return NormalizedPhoto(
        source_format, source_width, source_height, source_mode, orientation,
        moderation, mod_width, mod_height,
        web, web_width, web_height,
        thumbnail, thumb_width, thumb_height,
    )


def read_and_normalize(file_field):
    file_field.open("rb")
    try:
        return normalize_image_bytes(file_field.read())
    finally:
        file_field.close()
