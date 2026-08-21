from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import (
    Adventure,
    JournalEntry,
    MemberProfile,
    PotaActivationImport,
    PotaImportBatch,
)

from .pota_aggregation import aggregate_pota_journals, public_pota_leaders


class JournalDeletePotaRollupTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user("delete-owner", password="test")
        self.other = users.objects.create_user("delete-other", password="test")
        self.staff = users.objects.create_user(
            "delete-staff", password="test", is_staff=True
        )
        for user, callsign in (
            (self.owner, "W5DELETE"),
            (self.other, "N0OTHER"),
        ):
            MemberProfile.objects.create(
                user=user,
                callsign=callsign,
                callsign_verified=True,
                verification_method=MemberProfile.VerificationMethod.QRZ,
            )
        self.adventure = Adventure.objects.create(
            owner=self.owner, title="Delete Roll-Up", is_public=True
        )
        self.batch = PotaImportBatch.objects.create(owner=self.owner)

    def add_pota_journal(
        self, adventure, title, fingerprint, counts, *, batch=None
    ):
        journal = JournalEntry.objects.create(
            adventure=adventure,
            title=title,
            body="POTA Journal",
            pota=True,
            is_public=True,
        )
        activation = PotaActivationImport.objects.create(
            adventure=adventure,
            journal_entry=journal,
            batch=batch or self.batch,
            source=PotaImportBatch.Source.ACTIVATION_HISTORY,
            activation_date=date(2026, 8, 20),
            callsign="W5DELETE",
            park_reference=f"US-{journal.pk:04d}",
            park_name=title,
            cw_contacts=counts[0],
            data_contacts=counts[1],
            phone_contacts=counts[2],
            total_contacts=999,
            fingerprint=fingerprint,
            location_resolution="existing",
        )
        return journal, activation

    def totals(self, adventure):
        return aggregate_pota_journals(
            JournalEntry.objects.filter(adventure=adventure)
        )

    def leader(self, member_id):
        return next(
            (row for row in public_pota_leaders() if row["member_id"] == member_id),
            None,
        )

    def delete(self, journal, *, user=None):
        if user is not None:
            self.client.force_login(user)
        return self.client.post(reverse("delete_journal_entry", args=[journal.pk]))

    def test_deleting_pota_journal_updates_adventure_and_leaderboard(self):
        removed, _ = self.add_pota_journal(
            self.adventure, "Removed", "delete-removed", (2, 3, 5)
        )
        remaining, remaining_import = self.add_pota_journal(
            self.adventure, "Remaining", "delete-remaining", (7, 11, 13)
        )
        other_adventure = Adventure.objects.create(
            owner=self.other, title="Other Member", is_public=True
        )
        other_journal, other_import = self.add_pota_journal(
            other_adventure,
            "Other Journal",
            "delete-other",
            (17, 19, 23),
            batch=PotaImportBatch.objects.create(owner=self.other),
        )

        self.assertEqual(
            self.totals(self.adventure),
            {"cw": 9, "data": 14, "phone": 18, "total": 41},
        )
        self.assertEqual(self.leader(self.owner.pk)["total"], 41)

        response = self.delete(removed, user=self.owner)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.totals(self.adventure),
            {"cw": 7, "data": 11, "phone": 13, "total": 31},
        )
        owner_leader = self.leader(self.owner.pk)
        self.assertEqual(
            {key: owner_leader[key] for key in ("cw", "data", "phone", "total")},
            {"cw": 7, "data": 11, "phone": 13, "total": 31},
        )
        self.assertTrue(JournalEntry.objects.filter(pk=remaining.pk).exists())
        self.assertTrue(PotaActivationImport.objects.filter(pk=remaining_import.pk).exists())
        self.assertTrue(JournalEntry.objects.filter(pk=other_journal.pk).exists())
        self.assertTrue(PotaActivationImport.objects.filter(pk=other_import.pk).exists())
        self.assertEqual(self.leader(self.other.pk)["total"], 59)

    def test_deleting_final_pota_journal_produces_zero_totals(self):
        journal, _ = self.add_pota_journal(
            self.adventure, "Final", "delete-final", (3, 4, 5)
        )

        self.delete(journal, user=self.owner)

        self.assertEqual(
            self.totals(self.adventure),
            {"cw": 0, "data": 0, "phone": 0, "total": 0},
        )
        self.assertIsNone(self.leader(self.owner.pk))
        self.assertTrue(Adventure.objects.filter(pk=self.adventure.pk).exists())

    def test_deleting_non_pota_journal_does_not_change_pota_totals(self):
        _, activation = self.add_pota_journal(
            self.adventure, "POTA", "delete-keep-pota", (2, 4, 8)
        )
        ordinary = JournalEntry.objects.create(
            adventure=self.adventure,
            title="Ordinary",
            body="Not POTA",
            pota=False,
        )
        before = self.totals(self.adventure)

        self.delete(ordinary, user=self.owner)

        self.assertEqual(self.totals(self.adventure), before)
        self.assertTrue(PotaActivationImport.objects.filter(pk=activation.pk).exists())

    def test_unauthorized_and_anonymous_users_cannot_delete(self):
        journal, _ = self.add_pota_journal(
            self.adventure, "Protected", "delete-protected", (1, 1, 1)
        )

        anonymous = self.delete(journal)
        self.assertEqual(anonymous.status_code, 302)
        self.assertTrue(JournalEntry.objects.filter(pk=journal.pk).exists())

        denied = self.delete(journal, user=self.other)
        self.assertEqual(denied.status_code, 403)
        self.assertTrue(JournalEntry.objects.filter(pk=journal.pk).exists())

        allowed = self.delete(journal, user=self.staff)
        self.assertEqual(allowed.status_code, 302)
        self.assertFalse(JournalEntry.objects.filter(pk=journal.pk).exists())

    @patch("core.models.Adventure.save", side_effect=RuntimeError("update failed"))
    def test_post_delete_failure_rolls_back_journal_and_import(self, _save):
        journal, activation = self.add_pota_journal(
            self.adventure, "Rollback", "delete-rollback", (5, 6, 7)
        )
        self.client.force_login(self.owner)

        with self.assertRaisesMessage(RuntimeError, "update failed"):
            self.client.post(reverse("delete_journal_entry", args=[journal.pk]))

        self.assertTrue(JournalEntry.objects.filter(pk=journal.pk).exists())
        self.assertTrue(PotaActivationImport.objects.filter(pk=activation.pk).exists())
        self.assertEqual(
            self.totals(self.adventure),
            {"cw": 5, "data": 6, "phone": 7, "total": 18},
        )
