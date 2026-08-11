from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse

from .member_deletion import delete_member_account
from .models import (
    Adventure,
    CoordinateChangeAudit,
    JournalContact,
    JournalEntry,
    MemberProfile,
    PhotoModerationActionAudit,
    PolicyAcceptance,
    PotaActivationImport,
    PotaCallsignAttestation,
    PotaImportBatch,
    QuarantinedPhoto,
)


class MemberDeletionTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_superuser(
            username="delete-admin",
            password="StrongPass!942",
            email="admin@example.com",
        )
        self.member = user_model.objects.create_user(
            username="delete-member",
            password="StrongPass!942",
        )
        self.profile = MemberProfile.objects.create(
            user=self.member,
            callsign="W5DELETE",
        )
        self.delete_url = reverse("member_delete", args=[self.profile.pk])

    def _add_pota_history(self):
        adventure = Adventure.objects.create(
            owner=self.member,
            title="Imported activation",
        )
        journal = JournalEntry.objects.create(
            adventure=adventure,
            title="POTA contacts",
            body="Imported contacts",
        )
        JournalContact.objects.create(
            journal_entry=journal,
            qso_date=date(2026, 8, 11),
            callsign="W1TEST",
            fingerprint="delete-contact",
        )
        batch = PotaImportBatch.objects.create(owner=self.member)
        attestation = PotaCallsignAttestation.objects.create(
            batch=batch,
            member=self.member,
            callsign="W5DELETE",
            attestation_text="Authorized",
        )
        activation = PotaActivationImport.objects.create(
            adventure=adventure,
            batch=batch,
            activation_date=date(2026, 8, 11),
            callsign="W5DELETE",
            park_reference="US-0001",
            park_name="Deletion Test Park",
            total_contacts=1,
            fingerprint="delete-activation",
            location_resolution="unresolved",
        )
        return adventure, journal, batch, attestation, activation

    def _confirm_delete(self, *, follow=False):
        self.client.force_login(self.admin)
        return self.client.post(
            self.delete_url,
            {"confirmation": "DELETE MEMBER"},
            follow=follow,
        )

    def test_normal_member_without_related_records_deletes_successfully(self):
        response = self._confirm_delete(follow=True)

        self.assertFalse(get_user_model().objects.filter(pk=self.member.pk).exists())
        self.assertRedirects(response, reverse("member_admin_list"))
        self.assertContains(response, "Member deleted: W5DELETE")
        self.assertContains(response, "POTA import records deleted: 0")

    def test_member_with_pota_history_deletes_without_orphans(self):
        adventure, journal, batch, attestation, activation = self._add_pota_history()
        contact_pk = journal.contacts.values_list("pk", flat=True).get()

        response = self._confirm_delete(follow=True)

        self.assertEqual(response.status_code, 200)
        for model, pk in (
            (get_user_model(), self.member.pk),
            (Adventure, adventure.pk),
            (JournalEntry, journal.pk),
            (JournalContact, contact_pk),
            (PotaImportBatch, batch.pk),
            (PotaCallsignAttestation, attestation.pk),
            (PotaActivationImport, activation.pk),
        ):
            with self.subTest(model=model.__name__):
                self.assertFalse(model.objects.filter(pk=pk).exists())

    def test_protected_operational_audits_are_explicitly_removed(self):
        photo_audit = PhotoModerationActionAudit.objects.create(
            actor=self.member,
            action="approve",
            decision_source="manual",
            scope="selected",
        )
        coordinate_audit = CoordinateChangeAudit.objects.create(
            actor=self.member,
            record_type="location",
            record_id=42,
        )
        quarantine = QuarantinedPhoto.objects.create(
            original_kind=QuarantinedPhoto.Kind.PROFILE,
            original_object_id=self.profile.pk,
            original_target="profile_photo",
            association_label="W5DELETE",
            image="photo_quarantine/deleted-test.jpg",
            removal_reason="member_deleted",
            removed_by=self.member,
        )

        self._confirm_delete()

        self.assertFalse(PhotoModerationActionAudit.objects.filter(pk=photo_audit.pk).exists())
        self.assertFalse(CoordinateChangeAudit.objects.filter(pk=coordinate_audit.pk).exists())
        self.assertFalse(QuarantinedPhoto.objects.filter(pk=quarantine.pk).exists())

    def test_policy_history_is_preserved_and_anonymized(self):
        acceptance = PolicyAcceptance.objects.create(
            user=self.member,
            account_identifier="delete-member",
            terms_version="1",
            privacy_version="1",
            community_version="1",
            registration_path="member",
            age_attested=True,
            account_status="active",
        )

        self._confirm_delete()

        acceptance.refresh_from_db()
        self.assertIsNone(acceptance.user_id)
        self.assertEqual(acceptance.account_identifier, "delete-member")

    def test_superuser_and_staff_accounts_are_protected(self):
        user_model = get_user_model()
        staff = user_model.objects.create_user(
            username="protected-staff",
            password="StrongPass!942",
            is_staff=True,
        )
        staff_profile = MemberProfile.objects.create(user=staff, callsign="W5STAFF")

        self.client.force_login(self.admin)
        for profile, user in ((staff_profile, staff),):
            with self.subTest(username=user.username):
                response = self.client.post(
                    reverse("member_delete", args=[profile.pk]),
                    {"confirmation": "DELETE MEMBER"},
                    follow=True,
                )
                self.assertTrue(user_model.objects.filter(pk=user.pk).exists())
                self.assertContains(response, "cannot be deleted here")

        second_admin = user_model.objects.create_superuser(
            username="protected-admin",
            password="StrongPass!942",
            email="second@example.com",
        )
        admin_profile = MemberProfile.objects.create(
            user=second_admin,
            callsign="W5ADMIN",
        )
        response = self.client.get(
            reverse("member_delete", args=[admin_profile.pk]),
            follow=True,
        )
        self.assertTrue(user_model.objects.filter(pk=second_admin.pk).exists())
        self.assertContains(response, "cannot be deleted here")

    def test_unauthorized_user_cannot_delete_member(self):
        unauthorized = get_user_model().objects.create_user(
            username="not-staff",
            password="StrongPass!942",
        )
        self.client.force_login(unauthorized)

        response = self.client.post(
            self.delete_url,
            {"confirmation": "DELETE MEMBER"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(get_user_model().objects.filter(pk=self.member.pk).exists())

    def test_deletion_is_atomic_when_cleanup_fails(self):
        _, _, batch, _, activation = self._add_pota_history()

        def partial_cleanup_then_fail(user, deleted_counts):
            PotaActivationImport.objects.filter(pk=activation.pk).delete()
            raise RuntimeError("simulated cleanup failure")

        with patch(
            "core.member_deletion._delete_protected_operational_records",
            side_effect=partial_cleanup_then_fail,
        ):
            with self.assertRaises(RuntimeError):
                delete_member_account(self.member)

        self.assertTrue(get_user_model().objects.filter(pk=self.member.pk).exists())
        self.assertTrue(PotaImportBatch.objects.filter(pk=batch.pk).exists())
        self.assertTrue(PotaActivationImport.objects.filter(pk=activation.pk).exists())

    def test_protected_error_is_handled_without_raw_error_page(self):
        self.client.force_login(self.admin)
        with patch(
            "core.member_views.delete_member_account",
            side_effect=ProtectedError("simulated", set()),
        ):
            response = self.client.post(
                self.delete_url,
                {"confirmation": "DELETE MEMBER"},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "could not be safely removed")
        self.assertNotContains(response, "ProtectedError")
        self.assertTrue(get_user_model().objects.filter(pk=self.member.pk).exists())

    def test_confirmation_describes_pota_and_operational_history(self):
        self._add_pota_history()
        self.client.force_login(self.admin)

        response = self.client.get(self.delete_url)

        self.assertContains(response, "POTA import batches")
        self.assertContains(response, "POTA activation imports")
        self.assertContains(response, "1 POTA import batch")
        self.assertContains(response, "DELETE MEMBER")
