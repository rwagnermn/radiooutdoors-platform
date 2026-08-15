from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.models import Adventure, JournalEntry, MemberProfile, Photo


class JournalPhotoManagementTests(TestCase):
    def setUp(self):
        self.temp_media = TemporaryDirectory()
        self.addCleanup(self.temp_media.cleanup)
        media_override = override_settings(MEDIA_ROOT=self.temp_media.name)
        media_override.enable()
        self.addCleanup(media_override.disable)
        users = get_user_model().objects
        self.owner = users.create_user("photo-owner", password="test")
        self.other = users.create_user("photo-other", password="test")
        self.staff = users.create_user("photo-staff", password="test", is_staff=True)
        for user in (self.owner, self.other):
            MemberProfile.objects.create(
                user=user,
                callsign=user.username.upper(),
                callsign_verified=True,
                verification_method=MemberProfile.VerificationMethod.QRZ,
            )
        self.adventure = Adventure.objects.create(owner=self.owner, title="Photo Adventure", is_public=True)
        self.entry = JournalEntry.objects.create(adventure=self.adventure, title="Photo Journal", body="Photos", is_public=True)
        self.other_entry = JournalEntry.objects.create(adventure=self.adventure, title="Other Journal", body="Other", is_public=True)
        self.gallery_url = reverse("journal_photo_gallery", args=[self.entry.pk])

    def photo(self, entry=None, status=Photo.ModerationStatus.APPROVED, name=None, present=True):
        entry = entry or self.entry
        name = name or f"photo-{Photo.objects.count() + 1}.gif"
        photo = Photo.objects.create(
            journal_entry=entry,
            image=f"adventure_photos/{name}",
            moderation_status=status,
        )
        if present:
            target = Path(self.temp_media.name) / photo.image.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"GIF89a-valid-image-content")
        return photo

    def test_approved_photo_renders_and_media_returns_image(self):
        photo = self.photo()
        response = self.client.get(self.gallery_url)
        self.assertContains(response, photo.public_image_url)
        self.assertContains(response, photo.image.url)
        media = self.client.get(photo.public_image_url)
        self.assertEqual(media.status_code, 200)
        self.assertTrue(media["Content-Type"].startswith("image/"))
        media.close()

    def test_missing_media_has_explanatory_fallback(self):
        photo = self.photo(present=False)
        response = self.client.get(self.gallery_url)
        self.assertContains(response, "Photo unavailable")
        self.assertContains(response, "stored image file is missing or unreadable")
        self.assertNotContains(response, f'<img src="{photo.public_image_url}')

    def test_private_journal_media_is_not_exposed_by_known_url(self):
        self.entry.is_public = False
        self.entry.save(update_fields=["is_public"])
        photo = self.photo()
        self.assertEqual(self.client.get(photo.image.url).status_code, 404)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(photo.image.url).status_code, 404)
        self.client.force_login(self.owner)
        owner_media = self.client.get(photo.image.url)
        self.assertEqual(owner_media.status_code, 200)
        owner_media.close()

    def test_pending_and_rejected_are_owner_only_and_staff_gallery_is_unblurred(self):
        pending = self.photo(status=Photo.ModerationStatus.PENDING)
        rejected = self.photo(status=Photo.ModerationStatus.REJECTED)
        visitor = self.client.get(self.gallery_url)
        self.assertNotContains(visitor, pending.image.url)
        self.assertNotContains(visitor, rejected.image.url)
        self.client.force_login(self.owner)
        owner = self.client.get(self.gallery_url)
        self.assertContains(owner, "journal-photo-unapproved", count=2)
        self.client.force_login(self.staff)
        staff = self.client.get(self.gallery_url)
        self.assertNotContains(staff, "journal-photo-unapproved")
        self.assertContains(staff, pending.image.url)

    def test_management_controls_are_owner_and_staff_only_without_native_confirm(self):
        photo = self.photo()
        visitor = self.client.get(self.gallery_url)
        self.assertNotContains(visitor, "Delete Photo")
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(self.gallery_url), "Delete Photo")
        for user in (self.owner, self.staff):
            self.client.force_login(user)
            response = self.client.get(self.gallery_url)
            self.assertContains(response, "Select All")
            self.assertContains(response, "Clear Selection")
            self.assertContains(response, "Delete Selected Photos")
            self.assertContains(response, "Delete All Photos")
            self.assertContains(response, photo.reference_number)
        script = (Path(__file__).parents[1] / "static/js/journal-photo-management.js").read_text(encoding="utf-8")
        self.assertNotIn("window.confirm", script)
        self.assertNotIn("confirm(", script)
        self.assertIn("data-photo-select-all", script)
        self.assertIn("data-photo-clear", script)

    def test_delete_selected_is_atomic_and_limited_to_current_journal(self):
        first, second = self.photo(), self.photo()
        foreign = self.photo(entry=self.other_entry)
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("delete_journal_photos", args=[self.entry.pk]),
            {"delete_mode": "selected", "photo_ids": [first.pk]},
        )
        self.assertRedirects(response, self.gallery_url)
        self.assertFalse(Photo.objects.filter(pk=first.pk).exists())
        self.assertTrue(Photo.objects.filter(pk=second.pk).exists())
        self.assertTrue(Photo.objects.filter(pk=foreign.pk).exists())
        forged = self.client.post(
            reverse("delete_journal_photos", args=[self.entry.pk]),
            {"delete_mode": "selected", "photo_ids": [second.pk, foreign.pk]},
        )
        self.assertEqual(forged.status_code, 400)
        self.assertTrue(Photo.objects.filter(pk=second.pk).exists())
        self.assertTrue(Photo.objects.filter(pk=foreign.pk).exists())

    def test_delete_all_empties_only_current_journal_and_updates_count(self):
        cover = self.photo()
        self.photo()
        foreign = self.photo(entry=self.other_entry)
        self.adventure.cover_photo = cover
        self.adventure.cover_photo_is_explicit = True
        self.adventure.save(update_fields=["cover_photo", "cover_photo_is_explicit"])
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("delete_journal_photos", args=[self.entry.pk]),
            {"delete_mode": "all"},
            follow=True,
        )
        self.assertEqual(self.entry.photos.count(), 0)
        self.adventure.refresh_from_db()
        self.assertIsNone(self.adventure.cover_photo_id)
        self.assertFalse(self.adventure.cover_photo_is_explicit)
        self.assertTrue(Photo.objects.filter(pk=foreign.pk).exists())
        self.assertContains(response, "Deleted 2 all photos")
        self.assertContains(response, "No photos have been added to this Journal.")
        self.assertContains(response, "Add Photo")

    def test_individual_delete_requires_post_csrf_and_authorization(self):
        photo = self.photo()
        url = reverse("delete_photo", args=[photo.pk])
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(csrf_client.post(url).status_code, 403)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertTrue(Photo.objects.filter(pk=photo.pk).exists())

    def test_gallery_keeps_role_controls_and_original_viewing_out_of_compact_panel(self):
        photo = self.photo()
        self.client.force_login(self.owner)
        gallery = self.client.get(self.gallery_url)
        detail = self.client.get(reverse("journal_entry_detail", args=[self.entry.pk]))
        self.assertContains(gallery, "Use as Adventure Photo")
        self.assertContains(gallery, "Use as Journal Photo")
        self.assertContains(gallery, f'data-full-src="{photo.image.url}')
        self.assertNotContains(detail, "Use as Adventure Photo")
        self.assertNotContains(detail, "Use as Journal Photo")
