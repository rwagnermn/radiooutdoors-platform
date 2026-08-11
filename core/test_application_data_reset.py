from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .application_data_reset import reset_all_application_data
from .models import (
    Adventure, AdventureCoverSelectionAudit, BlockedDomain, Comment,
    CoordinateChangeAudit, DefaultLocationImage, FollowRelationship,
    FollowerInvitation, JournalContact, JournalEntry, Location, LocationType,
    ManualVerificationRequest, MemberCallsignAudit, MemberProfile,
    OperatingLocation, Photo, PhotoModerationActionAudit, PolicyAcceptance,
    PotaActivationImport, PotaCallsignAttestation, PotaImportBatch,
    PotaTestResetAudit, QuarantinedPhoto,
)


class ApplicationDataResetTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.member = users.create_user("member", password="member-pass")
        self.staff = users.create_user("staff", password="staff-pass", is_staff=True)
        self.superuser = users.create_superuser("root", "root@example.com", "root-pass")
        self.member_profile = MemberProfile.objects.create(user=self.member, callsign="N0MEM")
        self.staff_profile = MemberProfile.objects.create(user=self.staff, callsign="N0STAFF")
        self.super_profile = MemberProfile.objects.create(user=self.superuser, callsign="N0ROOT")
        self.location_type = LocationType.objects.get(name="Park")
        self.default_image, _ = DefaultLocationImage.objects.get_or_create(key="park", defaults={
            "source_title": "Reference", "source_url": "https://example.com/source",
            "creator": "Creator", "license_name": "License",
            "license_url": "https://example.com/license",
        })
        self.blocked_domain = BlockedDomain.objects.create(domain="blocked.example")

    def populate_operational_graph(self):
        location = Location.objects.create(name="Test Location", created_by=self.member)
        operating = OperatingLocation.objects.create(location=location, name="North Lot")
        adventure = Adventure.objects.create(owner=self.staff, title="Admin-owned data", location=location, operating_location=operating)
        journal = JournalEntry.objects.create(adventure=adventure, body="Journal")
        contact = JournalContact.objects.create(journal_entry=journal, qso_date="2026-01-01", callsign="W1AW", fingerprint="f" * 64)
        photo = Photo.objects.create(journal_entry=journal, image="adventure_photos/test.jpg")
        adventure.cover_photo = photo
        adventure.save(update_fields=["cover_photo"])
        Comment.objects.create(adventure=adventure, operator=self.member, body="Comment")
        batch = PotaImportBatch.objects.create(owner=self.member)
        PotaCallsignAttestation.objects.create(batch=batch, member=self.member, callsign="N0MEM", attestation_text="Attested")
        PotaActivationImport.objects.create(
            adventure=adventure, batch=batch, activation_date="2026-01-01", callsign="N0MEM",
            park_reference="US-0001", park_name="Park", fingerprint="a" * 64,
            location_resolution="existing",
        )
        PotaTestResetAudit.objects.create(staff_user=self.staff, database_identifier="test")
        PhotoModerationActionAudit.objects.create(actor=self.staff, action="approve", decision_source="staff", scope="photo")
        AdventureCoverSelectionAudit.objects.create(adventure=adventure, photo=photo, actor=self.staff)
        CoordinateChangeAudit.objects.create(actor=self.staff, record_type="location", record_id=location.pk)
        QuarantinedPhoto.objects.create(
            original_kind="photo", original_object_id=photo.pk, original_target="photo",
            association_label="Test", image="photo_quarantine/test.jpg", removal_reason="test",
            removed_by=self.staff,
        )
        ManualVerificationRequest.objects.create(
            member=self.member_profile, full_name="Member", country="USA",
            authority_url="https://example.com/license",
        )
        MemberCallsignAudit.objects.create(member=self.member_profile, old_callsign="OLD", new_callsign="N0MEM", changed_by=self.staff)
        FollowRelationship.objects.create(member=self.staff_profile, follower=self.member)
        FollowerInvitation.objects.create(member=self.staff_profile, name="Invitee", email="invitee@example.com", token="token")
        PolicyAcceptance.objects.create(
            user=self.member, account_identifier="member", terms_version="1", privacy_version="1",
            community_version="1", registration_path="signup", age_attested=True, account_status="active",
        )
        PolicyAcceptance.objects.create(
            user=self.superuser, account_identifier="root", terms_version="1", privacy_version="1",
            community_version="1", registration_path="admin", age_attested=True, account_status="active",
        )
        return photo

    def test_service_deletes_operational_data_and_preserves_admins_and_reference_data(self):
        self.populate_operational_graph()
        result = reset_all_application_data()
        users = get_user_model().objects
        self.assertFalse(users.filter(pk=self.member.pk).exists())
        self.assertTrue(users.filter(pk=self.staff.pk).exists())
        self.assertTrue(users.filter(pk=self.superuser.pk).exists())
        self.assertEqual(MemberProfile.objects.filter(pk__in=[self.staff_profile.pk, self.super_profile.pk]).count(), 2)
        self.assertEqual(PolicyAcceptance.objects.count(), 1)
        for model in (
            Adventure, AdventureCoverSelectionAudit, Comment, CoordinateChangeAudit,
            FollowRelationship, FollowerInvitation, JournalContact, JournalEntry, Location,
            ManualVerificationRequest, MemberCallsignAudit, OperatingLocation, Photo,
            PhotoModerationActionAudit, PotaActivationImport, PotaCallsignAttestation,
            PotaImportBatch, PotaTestResetAudit, QuarantinedPhoto,
        ):
            self.assertEqual(model.objects.count(), 0, model.__name__)
        self.assertTrue(LocationType.objects.filter(pk=self.location_type.pk).exists())
        self.assertTrue(DefaultLocationImage.objects.filter(pk=self.default_image.pk).exists())
        self.assertTrue(BlockedDomain.objects.filter(pk=self.blocked_domain.pk).exists())
        self.assertEqual(len(result.preserved_admins), 2)
        self.assertTrue(self.client.login(username="staff", password="staff-pass"))
        self.assertTrue(self.client.login(username="root", password="root-pass"))

    def test_only_superuser_can_access_or_execute_and_get_never_executes(self):
        self.populate_operational_graph()
        url = reverse("reset_all_application_data")
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {"confirmation_phrase": "DELETE ALL DATA"}).status_code, 403)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertTrue(Adventure.objects.exists())

    def test_confirmation_must_match_exactly_and_correct_confirmation_resets(self):
        self.populate_operational_graph()
        self.client.force_login(self.superuser)
        url = reverse("reset_all_application_data")
        bad = self.client.post(url, {"confirmation_phrase": "delete all data"})
        self.assertEqual(bad.status_code, 400)
        self.assertTrue(Adventure.objects.exists())
        good = self.client.post(url, {"confirmation_phrase": "DELETE ALL DATA"})
        self.assertEqual(good.status_code, 200)
        self.assertContains(good, "Application Data Reset Complete")
        self.assertContains(good, "root@example.com")
        self.assertFalse(Adventure.objects.exists())

    def test_uploaded_and_orphaned_operational_media_are_removed(self):
        with TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                photo = self.populate_operational_graph()
                photo.image.save("record.jpg", ContentFile(b"record"), save=True)
                self.super_profile.profile_photo.save("admin.jpg", ContentFile(b"admin"), save=True)
                preserved_profile_photo = Path(self.super_profile.profile_photo.path)
                orphan = Path(media_root) / "adventure_photos" / "orphan.jpg"
                orphan.parent.mkdir(parents=True, exist_ok=True)
                orphan.write_bytes(b"orphan")
                static_like = Path(media_root) / "location_defaults" / "preserved.jpg"
                static_like.parent.mkdir(parents=True, exist_ok=True)
                static_like.write_bytes(b"preserved")
                result = reset_all_application_data()
                self.assertFalse(Path(photo.image.path).exists())
                self.assertFalse(orphan.exists())
                self.assertTrue(static_like.exists())
                self.assertTrue(preserved_profile_photo.exists())
                self.assertGreaterEqual(result.media_files_deleted, 2)

    def test_superuser_navigation_entry_is_hidden_from_staff(self):
        self.client.force_login(self.staff)
        staff_home = self.client.get(reverse("home"))
        self.assertContains(staff_home, "Admin Tools")
        self.assertContains(staff_home, "Location Types")
        self.assertContains(staff_home, "Photo Moderation")
        self.assertContains(staff_home, "POTA Pin Review")
        self.assertContains(staff_home, "User / Member Administration")
        self.assertContains(staff_home, "Manual Verification Queue")
        self.assertContains(staff_home, "Default Location Images")
        self.assertContains(staff_home, "Stewardship")
        self.assertContains(staff_home, 'class="admin-tools-menu"')
        self.assertContains(staff_home, 'class="admin-tools-chevron"')
        self.assertNotContains(staff_home, '<details class="admin-tools-menu" open>')
        self.assertNotContains(staff_home, "Reset All Application Data")
        self.client.force_login(self.superuser)
        superuser_home = self.client.get(reverse("home"))
        self.assertContains(superuser_home, 'class="admin-tools-destructive-separator"')
        self.assertContains(superuser_home, "Reset All Application Data")
