from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import (
    Adventure, AdventureCoverSelectionAudit, JournalEntry, MemberProfile, Photo,
)


class AdventureCoverTests(TestCase):
    def setUp(self):
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
        return Photo.objects.create(
            journal_entry=entry, image=f"test/{name}.jpg",
            moderation_status=status, display_order=order,
        )

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
        gallery = self.client.get(self.adventure.get_absolute_url())
        self.assertContains(gallery, "Use as Adventure Cover")
        self.assertContains(gallery, "Journal: Adventure photos")
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
