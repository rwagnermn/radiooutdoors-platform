from io import BytesIO
import os
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import Adventure, JournalEntry, Location, MemberProfile, Photo
from .photo_moderation import moderate_photo, validate_image_file
from .photo_normalization import ImageNormalizationError, normalize_image_bytes


def encoded_image(fmt="JPEG", *, mode="RGB", size=(120, 80), exif=None):
    image = Image.new(mode, size, (30, 90, 140) if mode == "RGB" else 20)
    output = BytesIO()
    options = {}
    if fmt == "JPEG":
        options["quality"] = 90
    if exif:
        options["exif"] = exif
    image.save(output, fmt, **options)
    return output.getvalue()


class CaptureSafeProvider:
    provider_name = "Test"
    model = "test-image-model"
    last_content_type = ""
    last_size = 0

    def moderate(self, image_bytes, *, content_type=""):
        from .photo_moderation import ModerationDecision
        type(self).last_content_type = content_type
        type(self).last_size = len(image_bytes)
        return ModerationDecision(
            "approved", [], 0.01, "", "safe", self.provider_name, self.model
        )


class PhotoNormalizationUnitTests(TestCase):
    def upload(self, name, payload, content_type="application/octet-stream"):
        return SimpleUploadedFile(name, payload, content_type=content_type)

    def test_jpg_jpeg_uppercase_and_wrong_extension_use_decoded_bytes(self):
        payload = encoded_image("JPEG")
        for name in ("photo.jpg", "photo.jpeg", "photo.JPG", "photo.bin"):
            self.assertEqual(validate_image_file(self.upload(name, payload)), "JPEG")

    def test_png_webp_and_nonanimated_gif_are_supported(self):
        for fmt, name in (("PNG", "p.png"), ("WEBP", "p.webp"), ("GIF", "p.gif")):
            self.assertEqual(validate_image_file(self.upload(name, encoded_image(fmt))), fmt)

    def test_animated_gif_is_rejected(self):
        first = Image.new("RGB", (20, 20), "red")
        second = Image.new("RGB", (20, 20), "blue")
        output = BytesIO()
        first.save(output, "GIF", save_all=True, append_images=[second], duration=100)
        with self.assertRaises(ImageNormalizationError) as captured:
            normalize_image_bytes(output.getvalue())
        self.assertEqual(captured.exception.category, "animated_image")

    def test_valid_original_over_twenty_mb_is_normalized_below_provider_limit(self):
        raw = os.urandom(3000 * 3000 * 3)
        image = Image.frombytes("RGB", (3000, 3000), raw)
        output = BytesIO()
        image.save(output, "PNG", compress_level=0)
        payload = output.getvalue()
        self.assertGreater(len(payload), 20 * 1024 * 1024)
        normalized = normalize_image_bytes(payload)
        self.assertLess(len(normalized.moderation_bytes), 5 * 1024 * 1024)
        self.assertLessEqual(max(normalized.moderation_width, normalized.moderation_height), 2560)

    def test_cmyk_jpeg_normalizes_to_rgb_jpeg(self):
        normalized = normalize_image_bytes(encoded_image("JPEG", mode="CMYK"))
        self.assertEqual(normalized.source_mode, "CMYK")
        with Image.open(BytesIO(normalized.moderation_bytes)) as result:
            self.assertEqual((result.format, result.mode), ("JPEG", "RGB"))

    def test_exif_orientation_is_applied_and_removed(self):
        exif = Image.Exif()
        exif[274] = 6
        normalized = normalize_image_bytes(encoded_image("JPEG", size=(120, 80), exif=exif))
        self.assertEqual((normalized.moderation_width, normalized.moderation_height), (80, 120))
        with Image.open(BytesIO(normalized.moderation_bytes)) as result:
            self.assertIsNone(result.getexif().get(274))

    def test_invalid_corrupt_and_excessive_dimensions_have_distinct_categories(self):
        with self.assertRaises(ImageNormalizationError) as invalid:
            normalize_image_bytes(b"not an image")
        self.assertEqual(invalid.exception.category, "invalid_image")
        with self.assertRaises(ImageNormalizationError) as corrupt:
            normalize_image_bytes(encoded_image("JPEG")[:30])
        self.assertIn(corrupt.exception.category, {"damaged_image", "invalid_image"})
        with self.settings(PHOTO_MAX_PIXELS=100):
            with self.assertRaises(ImageNormalizationError) as large:
                normalize_image_bytes(encoded_image("PNG", size=(20, 20)))
        self.assertEqual(large.exception.category, "image_too_large")

    def test_heic_without_decoder_has_specific_message(self):
        payload = b"\x00\x00\x00\x18ftypheic" + (b"\x00" * 32)
        with self.assertRaises(ImageNormalizationError) as captured:
            normalize_image_bytes(payload)
        self.assertEqual(captured.exception.category, "heic_conversion_unavailable")
        self.assertIn("iPhone photo uses HEIC", captured.exception.messages[0])


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(),
    PHOTO_MODERATION_BACKEND="core.test_photo_normalization.CaptureSafeProvider",
)
class PhotoDerivativeAndReferenceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("photo-owner", password="secret")
        MemberProfile.objects.create(user=self.user, callsign="N0PHOTO", callsign_verified=True)
        location = Location.objects.create(name="Photo Test Site")
        adventure = Adventure.objects.create(owner=self.user, title="Photo Test", location=location)
        self.entry = JournalEntry.objects.create(adventure=adventure, title="Entry", body="Notes")

    def make_photo(self):
        return Photo.objects.create(
            journal_entry=self.entry,
            image=SimpleUploadedFile("camera.JPG", encoded_image("JPEG", size=(3200, 1800)), content_type="image/jpeg"),
            original_filename="camera.JPG",
            original_content_type="image/jpeg",
        )

    def test_derivatives_reference_and_provider_payload(self):
        photo = self.make_photo()
        original_name = photo.image.name
        moderate_photo(photo)
        photo.refresh_from_db()
        self.assertEqual(photo.reference_number, f"RO-PH-{photo.pk:06d}")
        self.assertEqual(photo.image.name, original_name)
        self.assertEqual(photo.derivative_status, "ready")
        self.assertTrue(photo.moderation_image and photo.web_image and photo.thumbnail_image)
        self.assertLess(photo.derivative_metadata["moderation_bytes"], 5 * 1024 * 1024)
        self.assertLessEqual(max(photo.derivative_metadata["moderation_dimensions"]), 2560)
        self.assertEqual(CaptureSafeProvider.last_content_type, "image/jpeg")
        self.assertEqual(CaptureSafeProvider.last_size, photo.derivative_metadata["moderation_bytes"])
        self.assertEqual(photo.moderation_status, "approved")

    def test_retry_reuses_existing_derivative(self):
        photo = self.make_photo()
        moderate_photo(photo)
        photo.refresh_from_db()
        stored_name = photo.moderation_image.name
        moderate_photo(photo)
        photo.refresh_from_db()
        self.assertEqual(photo.moderation_image.name, stored_name)

    @override_settings(
        PHOTO_MODERATION_BACKEND="core.photo_moderation.DisabledModerationProvider"
    )
    def test_failed_moderation_derivatives_remain_private(self):
        photo = self.make_photo()
        moderate_photo(photo)
        photo.refresh_from_db()
        self.assertEqual(photo.automated_decision, "scan_failed")
        self.assertEqual(photo.derivative_status, "ready")
        self.assertFalse(photo.is_publicly_visible)
        self.assertEqual(self.client.get(photo.web_image.url).status_code, 404)
        self.assertEqual(self.client.get(photo.thumbnail_image.url).status_code, 404)

    def test_reference_search_accepts_formatted_and_numeric_values(self):
        photo = self.make_photo()
        staff = get_user_model().objects.create_user("photo-staff", password="secret", is_staff=True)
        self.client.force_login(staff)
        for query in (photo.reference_number, str(photo.pk)):
            response = self.client.get(reverse("photo_moderation_queue"), {"q": query})
            self.assertContains(response, photo.reference_number)
        self.client.force_login(self.user)
        self.assertEqual(
            self.client.get(reverse("photo_moderation_queue"), {"q": str(photo.pk)}).status_code,
            302,
        )
