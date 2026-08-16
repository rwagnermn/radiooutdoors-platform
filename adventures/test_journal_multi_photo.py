from io import BytesIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from core.models import Adventure, JournalEntry, MemberProfile, Photo


def image_upload(name, color):
    output = BytesIO()
    Image.new("RGB", (96, 72), color).save(output, format="JPEG")
    return SimpleUploadedFile(name, output.getvalue(), content_type="image/jpeg")


@override_settings(PHOTO_MODERATION_BACKEND="core.test_photo_moderation.SafeProvider")
class JournalMultiPhotoUploadTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="multi-photo-owner", password="test-password"
        )
        MemberProfile.objects.create(
            user=self.user,
            callsign="W0MULTI",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.client.force_login(self.user)
        self.adventure = Adventure.objects.create(
            owner=self.user,
            title="Multi-photo Adventure",
            operating_callsign="W0MULTI",
            is_public=False,
        )
        self.url = reverse("add_journal_entry", args=[self.adventure.slug])

    def post_photos(self, photos, follow=False):
        return self.client.post(
            self.url,
            {
                "entry_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
                "status": JournalEntry.Status.OPEN,
                "journal_visibility_present": "1",
                "location_name": "Portable test location",
                "latitude": "44.100000",
                "longitude": "-93.100000",
                "operating_callsign": "W0MULTI",
                "body": "Eight-photo upload test.",
                "photos": photos,
            },
            follow=follow,
        )

    def test_eight_files_create_eight_photos_on_one_journal(self):
        photos = [
            image_upload(f"clipboard-{index}.jpg", (index * 20, 40, 90))
            for index in range(1, 9)
        ]

        response = self.post_photos(photos)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(JournalEntry.objects.count(), 1)
        entry = JournalEntry.objects.get()
        self.assertEqual(entry.adventure, self.adventure)
        self.assertFalse(entry.is_public)
        self.assertEqual(entry.photos.count(), 8)
        self.assertEqual(Photo.objects.filter(journal_entry=entry).count(), 8)
        self.assertEqual(Photo.objects.filter(journal_entry__isnull=True).count(), 0)
        self.assertEqual(
            set(entry.photos.values_list("original_filename", flat=True)),
            {f"clipboard-{index}.jpg" for index in range(1, 9)},
        )

    def test_invalid_image_is_reported_while_valid_images_are_saved(self):
        response = self.post_photos(
            [
                image_upload("valid-one.jpg", "red"),
                SimpleUploadedFile("broken.jpg", b"not an image", "image/jpeg"),
                image_upload("valid-two.jpg", "blue"),
            ],
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        entry = JournalEntry.objects.get()
        self.assertEqual(entry.photos.count(), 2)
        self.assertContains(response, "2 photos added to the Journal Entry.")
        self.assertContains(response, "1 photo was rejected.")
        self.assertContains(response, "broken.jpg:")

    def test_another_member_cannot_add_photos_to_the_adventure(self):
        other = get_user_model().objects.create_user(
            username="multi-photo-other", password="test-password"
        )
        MemberProfile.objects.create(
            user=other,
            callsign="W0OTHER",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.client.force_login(other)

        response = self.post_photos([image_upload("blocked.jpg", "green")])

        self.assertEqual(response.status_code, 403)
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(Photo.objects.count(), 0)

    def test_multi_paste_client_collects_all_items_and_keeps_additive_state(self):
        response = self.client.get(self.url)

        self.assertContains(response, 'data-photo-preview-mode="multiple"')
        self.assertContains(response, 'data-photo-max-bytes="12582912"')
        self.assertContains(response, "Drag photos here, paste an image, or choose photos")
        self.assertContains(response, 'type="file"')
        self.assertContains(response, 'accept="image/*"')
        self.assertContains(response, "multiple")
        script = (settings.BASE_DIR / "static" / "js" / "photo-preview.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("Array.from(clipboard.items || [])", script)
        self.assertIn("item.getAsFile()", script)
        self.assertIn("Array.from(clipboard.files || [])", script)
        self.assertIn('existing.concat(images)', script)
        self.assertIn('readyMessage(combined.length)', script)
        self.assertIn("clipboardFiles.length > itemFiles.length", script)
        self.assertIn('pasteZone.addEventListener("dragenter"', script)
        self.assertIn('pasteZone.addEventListener("dragover"', script)
        self.assertIn('pasteZone.addEventListener("dragleave"', script)
        self.assertIn('pasteZone.addEventListener("drop"', script)
        self.assertIn("event.dataTransfer.files", script)
        self.assertIn("Firefox did not provide the copied files.", script)
