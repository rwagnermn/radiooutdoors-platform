from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import (
    Adventure,
    JournalContact,
    JournalEntry,
    MemberProfile,
    PotaActivationImport,
    PotaImportBatch,
)

from .pota_aggregation import aggregate_pota_journals, public_pota_leaders


class ImportedPotaHistoryManagementTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user("history-owner", password="test")
        self.other = users.objects.create_user("history-other", password="test")
        self.staff = users.objects.create_user(
            "history-staff", password="test", is_staff=True
        )
        for user, callsign in (
            (self.owner, "W5HISTORY"),
            (self.other, "N0HISTORY"),
        ):
            MemberProfile.objects.create(
                user=user,
                callsign=callsign,
                callsign_verified=True,
                verification_method=MemberProfile.VerificationMethod.QRZ,
            )
        self.adventure = Adventure.objects.create(
            owner=self.owner, title="History Adventure", is_public=True
        )
        self.journal = JournalEntry.objects.create(
            adventure=self.adventure,
            title="History Journal",
            body="Imported history",
            pota=True,
            is_public=True,
        )
        self.batch = PotaImportBatch.objects.create(
            owner=self.owner,
            source=PotaImportBatch.Source.ACTIVATION_HISTORY,
        )
        self.activation = self.activation_for(
            self.journal, self.batch, "history-primary", cw=2, data=3, phone=5
        )
        self.url = reverse("imported_pota_history", args=[self.journal.pk])

    def activation_for(self, journal, batch, fingerprint, *, cw=1, data=1, phone=1):
        return PotaActivationImport.objects.create(
            adventure=journal.adventure,
            journal_entry=journal,
            batch=batch,
            source=PotaImportBatch.Source.ACTIVATION_HISTORY,
            activation_date=date(2026, 8, 20),
            callsign="W5HISTORY",
            park_reference="US-1000",
            park_name="History Park",
            cw_contacts=cw,
            data_contacts=data,
            phone_contacts=phone,
            total_contacts=999,
            fingerprint=fingerprint,
            location_resolution="existing",
        )

    def other_activation(self, *, batch=None):
        adventure = Adventure.objects.create(
            owner=self.other, title="Other Adventure", is_public=True
        )
        journal = JournalEntry.objects.create(
            adventure=adventure,
            title="Other Journal",
            body="Other imported history",
            pota=True,
            is_public=True,
        )
        other_batch = batch or PotaImportBatch.objects.create(owner=self.other)
        return adventure, journal, self.activation_for(
            journal, other_batch, f"other-{journal.pk}", cw=4, data=5, phone=6
        )

    def test_owner_can_view_read_only_history_page(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<h1>Imported POTA History</h1>", html=True)
        self.assertContains(response, "History Journal")
        self.assertContains(response, "History Adventure")
        self.assertContains(response, "US-1000")
        self.assertNotContains(response, "type=\"text\"")

    def test_staff_has_access_but_unrelated_member_is_denied(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_anonymous_user_cannot_access(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_get_and_cancel_delete_nothing(self):
        self.client.force_login(self.owner)
        self.client.get(self.url)
        cancel = self.client.get(reverse("journal_entry_detail", args=[self.journal.pk]))
        self.assertEqual(cancel.status_code, 200)
        self.assertTrue(PotaActivationImport.objects.filter(pk=self.activation.pk).exists())

    def test_owner_deletes_selected_record_only(self):
        _, _, other = self.other_activation()
        ordinary = JournalContact.objects.create(
            journal_entry=self.journal,
            adventure=self.adventure,
            owner=self.owner,
            qso_date=date(2026, 8, 20),
            callsign="K0ORDINARY",
            fingerprint="ordinary-contact",
        )
        self.client.force_login(self.owner)
        response = self.client.post(
            self.url,
            {"delete_scope": "selected", "selected_records": [self.activation.pk]},
            follow=True,
        )
        self.assertContains(response, "Deleted 1 imported POTA History record.")
        self.assertFalse(PotaActivationImport.objects.filter(pk=self.activation.pk).exists())
        self.assertTrue(PotaActivationImport.objects.filter(pk=other.pk).exists())
        self.assertTrue(JournalContact.objects.filter(pk=ordinary.pk).exists())
        self.assertTrue(JournalEntry.objects.filter(pk=self.journal.pk).exists())
        self.assertTrue(Adventure.objects.filter(pk=self.adventure.pk).exists())

    def test_submitted_other_journal_id_is_safely_ignored(self):
        _, _, other = self.other_activation()
        self.client.force_login(self.owner)
        self.client.post(
            self.url,
            {"delete_scope": "selected", "selected_records": [other.pk]},
        )
        self.assertTrue(PotaActivationImport.objects.filter(pk=self.activation.pk).exists())
        self.assertTrue(PotaActivationImport.objects.filter(pk=other.pk).exists())

    def test_malformed_ids_and_batch_are_safely_ignored(self):
        self.client.force_login(self.owner)
        self.client.post(
            self.url,
            {"delete_scope": "selected", "selected_records": ["not-an-id", "-1"]},
        )
        self.client.post(
            self.url,
            {
                "delete_scope": "batch",
                "batch_id": "not-a-batch",
                "confirm_bulk": "yes",
            },
        )
        self.assertTrue(PotaActivationImport.objects.filter(pk=self.activation.pk).exists())

    def test_batch_delete_is_confirmed_and_cannot_escape_journal(self):
        _, _, other = self.other_activation(batch=self.batch)
        self.client.force_login(self.owner)
        self.client.post(
            self.url,
            {"delete_scope": "batch", "batch_id": self.batch.pk},
        )
        self.assertTrue(PotaActivationImport.objects.filter(pk=self.activation.pk).exists())
        self.assertEqual(
            aggregate_pota_journals(JournalEntry.objects.filter(pk=self.journal.pk)),
            {"cw": 2, "data": 3, "phone": 5, "total": 10},
        )
        self.client.post(
            self.url,
            {
                "delete_scope": "batch",
                "batch_id": self.batch.pk,
                "confirm_bulk": "yes",
            },
        )
        self.assertFalse(PotaActivationImport.objects.filter(pk=self.activation.pk).exists())
        self.assertTrue(PotaActivationImport.objects.filter(pk=other.pk).exists())

    def test_delete_all_is_confirmed_and_cannot_escape_journal(self):
        _, _, other = self.other_activation()
        self.client.force_login(self.owner)
        self.client.post(self.url, {"delete_scope": "all"})
        self.assertTrue(PotaActivationImport.objects.filter(pk=self.activation.pk).exists())
        self.client.post(
            self.url, {"delete_scope": "all", "confirm_bulk": "yes"}
        )
        self.assertFalse(PotaActivationImport.objects.filter(pk=self.activation.pk).exists())
        self.assertTrue(PotaActivationImport.objects.filter(pk=other.pk).exists())

    def test_rollups_recalculate_and_empty_history_is_zero(self):
        _, other_journal, _ = self.other_activation()
        self.client.force_login(self.owner)
        self.assertEqual(
            aggregate_pota_journals(JournalEntry.objects.filter(pk=self.journal.pk)),
            {"cw": 2, "data": 3, "phone": 5, "total": 10},
        )
        self.client.post(
            self.url, {"delete_scope": "all", "confirm_bulk": "yes"}
        )
        self.assertEqual(
            aggregate_pota_journals(JournalEntry.objects.filter(pk=self.journal.pk)),
            {"cw": 0, "data": 0, "phone": 0, "total": 0},
        )
        self.assertEqual(
            aggregate_pota_journals(
                JournalEntry.objects.filter(adventure=self.adventure)
            ),
            {"cw": 0, "data": 0, "phone": 0, "total": 0},
        )
        leaders = list(public_pota_leaders())
        self.assertFalse(any(row["member_id"] == self.owner.pk for row in leaders))
        self.assertTrue(any(row["member_id"] == other_journal.adventure.owner_id for row in leaders))

    @patch(
        "adventures.pota_history_management.recalculate_pota_rollups",
        side_effect=RuntimeError("recalculation failed"),
    )
    def test_recalculation_failure_rolls_back_deletion(self, _recalculate):
        self.client.force_login(self.owner)
        with self.assertRaisesMessage(RuntimeError, "recalculation failed"):
            self.client.post(
                self.url,
                {"delete_scope": "selected", "selected_records": [self.activation.pk]},
            )
        self.assertTrue(PotaActivationImport.objects.filter(pk=self.activation.pk).exists())

    def test_button_visibility_placement_and_condition(self):
        detail_url = reverse("journal_entry_detail", args=[self.journal.pk])
        history_link = f'<a href="{self.url}">Imported POTA History</a>'
        self.client.force_login(self.owner)
        owner = self.client.get(detail_url)
        self.assertContains(owner, history_link, html=True)
        source = owner.content.decode()
        self.assertLess(source.index(">View Map</a>"), source.index(history_link))

        self.client.force_login(self.staff)
        self.assertContains(self.client.get(detail_url), history_link, html=True)
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(detail_url), "Imported POTA History")
        self.client.logout()
        self.assertNotContains(self.client.get(detail_url), "Imported POTA History")

        self.activation.delete()
        self.client.force_login(self.owner)
        self.assertNotContains(self.client.get(detail_url), "Imported POTA History")
