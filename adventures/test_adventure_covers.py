from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import (
    Adventure, AdventureCoverSelectionAudit, JournalEntry, MemberProfile, Photo,
)


class AdventureCoverTests(TestCase):
    def setUp(self):
        self.temp_media = TemporaryDirectory()
        self.addCleanup(self.temp_media.cleanup)
        media_override = override_settings(MEDIA_ROOT=self.temp_media.name)
        media_override.enable()
        self.addCleanup(media_override.disable)
        users = get_user_model()
        self.owner = users.objects.create_user("W5COVER", password="test-password")
        MemberProfile.objects.create(
            user=self.owner, callsign="W5COVER", callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.other = users.objects.create_user("W5OTHER2", password="test-password")
        MemberProfile.objects.create(
            user=self.other, callsign="W5OTHER2", callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.adventure = Adventure.objects.create(
            owner=self.owner, title="Cover Test", is_public=True
        )

    def entry(self, title, direct=False, public=True):
        return JournalEntry.objects.create(
            adventure=self.adventure, title=title, body="Notes", is_public=public,
            is_adventure_photo_collection=direct,
        )

    def photo(self, entry, name, status="approved", order=0):
        photo = Photo.objects.create(
            journal_entry=entry, image=f"test/{name}.jpg",
            moderation_status=status, display_order=order,
        )
        target = Path(self.temp_media.name) / photo.image.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"image-content")
        return photo

    def test_generic_is_used_when_no_approved_photo_exists(self):
        pending = self.photo(self.entry("Adventure photos", direct=True), "pending", "pending")
        self.assertIsNone(self.adventure.display_cover_photo)
        response = self.client.get(self.adventure.get_absolute_url())
        self.assertContains(response, "images/hero.jpg")
        self.assertNotContains(response, pending.image.url)

    def test_direct_adventure_photo_precedes_journal_photo(self):
        journal = self.photo(self.entry("Field notes"), "journal")
        direct = self.photo(self.entry("Adventure photos", direct=True), "direct")
        self.assertEqual(self.adventure.display_cover_photo.pk, direct.pk)
        self.assertNotEqual(self.adventure.display_cover_photo.pk, journal.pk)

    def test_first_approved_journal_photo_is_fallback(self):
        pending = self.photo(self.entry("Adventure photos", direct=True), "pending", "pending")
        journal = self.photo(self.entry("Field notes"), "journal")
        self.assertEqual(self.adventure.display_cover_photo.pk, journal.pk)
        pending.moderation_status = "approved"
        pending.save(update_fields=["moderation_status"])
        self.assertEqual(self.adventure.display_cover_photo.pk, pending.pk)

    def test_owner_selection_persists_and_is_audited(self):
        entry = self.entry("Adventure photos", direct=True)
        first = self.photo(entry, "first", order=0)
        selected = self.photo(entry, "selected", order=1)
        self.client.force_login(self.owner)
        gallery = self.client.get(reverse("journal_photo_gallery", args=[entry.pk]))
        self.assertContains(gallery, "Use as Adventure Photo")
        self.assertContains(gallery, "Adventure photos Photos")
        response = self.client.post(reverse(
            "make_adventure_cover", args=[self.adventure.slug, selected.pk]
        ))
        self.assertRedirects(response, self.adventure.get_absolute_url())
        self.adventure.refresh_from_db()
        self.assertTrue(self.adventure.cover_photo_is_explicit)
        self.assertEqual(self.adventure.display_cover_photo.pk, selected.pk)
        self.photo(entry, "later", order=2)
        self.assertEqual(self.adventure.display_cover_photo.pk, selected.pk)
        self.assertTrue(AdventureCoverSelectionAudit.objects.filter(
            adventure=self.adventure, photo=selected, actor=self.owner
        ).exists())
        self.assertNotEqual(first.pk, selected.pk)

    def test_ineligible_selected_cover_falls_back_immediately(self):
        entry = self.entry("Adventure photos", direct=True)
        fallback = self.photo(entry, "fallback", order=0)
        selected = self.photo(entry, "selected", order=1)
        self.adventure.cover_photo = selected
        self.adventure.cover_photo_is_explicit = True
        self.adventure.save(update_fields=["cover_photo", "cover_photo_is_explicit"])
        selected.moderation_status = "rejected"
        selected.save(update_fields=["moderation_status"])
        self.assertEqual(self.adventure.display_cover_photo.pk, fallback.pk)

    def test_unauthorized_and_cross_adventure_selection_are_denied(self):
        photo = self.photo(self.entry("Journal"), "eligible")
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.post(reverse("make_cover_photo", args=[photo.pk])).status_code,
            403,
        )
        other_adventure = Adventure.objects.create(owner=self.other, title="Other")
        other_entry = JournalEntry.objects.create(
            adventure=other_adventure, title="Other", body="Notes"
        )
        other_photo = Photo.objects.create(
            journal_entry=other_entry, image="test/other.jpg", moderation_status="approved"
        )
        self.client.force_login(self.owner)
        response = self.client.post(reverse(
            "make_adventure_cover", args=[self.adventure.slug, other_photo.pk]
        ))
        self.assertEqual(response.status_code, 403)
        self.adventure.refresh_from_db()
        self.assertIsNone(self.adventure.cover_photo_id)

    def test_private_journal_photo_is_not_cover_eligible(self):
        private_photo = self.photo(self.entry("Private", public=False), "private")
        self.assertTrue(private_photo.is_publicly_visible)
        self.assertIsNone(self.adventure.display_cover_photo)

    def test_adventure_content_photos_are_reduced_without_changing_cover(self):
        css = (settings.BASE_DIR / "static" / "css" / "style.css").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            ".adventure-story-page .journal-photo-grid.adventure-photo-masonry",
            css,
        )
        self.assertIn("grid-template-columns:repeat(auto-fill,minmax(160px,200px))", css)
        self.assertIn(
            ".adventure-story-page .adventure-photo-masonry .journal-photo{max-width:200px}",
            css,
        )
        self.assertIn("height: clamp(210px, 21vw, 255px)", css)
        self.assertNotIn(".adventure-cover-frame .adventure-photo-masonry", css)

    def test_adventure_gallery_keeps_original_viewer_url_and_trigger(self):
        photo = self.photo(self.entry("Field notes"), "viewer")

        response = self.client.get(self.adventure.get_absolute_url())

        self.assertContains(response, 'class="journal-photo-viewer-trigger"')
        self.assertContains(response, f'data-full-src="{photo.image.url}')
        self.assertContains(response, "at original size")
