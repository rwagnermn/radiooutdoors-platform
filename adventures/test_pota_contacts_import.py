from datetime import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import (
    Adventure, JournalContact, JournalEntry, MemberProfile,
    PotaActivationImport, PotaImportBatch,
)
from core.qrz_service import QRZError
from .pota_import import parse_pota_activation_contacts


def contact_record(callsign="K3BAL", *, kind="Activator", timestamp="2026-08-21 16:39", combined=False):
    operator = f"N2JIM\t{callsign}" if combined else "N2JIM"
    contact = "" if combined else f"{callsign}\t"
    return "\r\n".join([
        f"{kind}\t{timestamp}\t", "N2JIM\t", operator,
        f"{contact}20M\tPHONE (SSB)\tUS-MN\tUS-11980 Bethel Wildlife Management Area",
    ])


class PotaActivationContactParserTests(TestCase):
    def test_supplied_fixture_parses_all_25_records_and_footer(self):
        fixture = Path(settings.BASE_DIR) / "adventures/test_fixtures/pota_contacts.txt"
        rows, invalid, metadata = parse_pota_activation_contacts(fixture.read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 25)
        self.assertEqual(invalid, [])
        self.assertEqual(metadata, {"pasted_count": 25, "range_start": 1, "range_end": 25, "total_shown": 109})
        callsigns = [row["worked_callsign"] for row in rows]
        for callsign in ("K3BAL", "KD3CNZ", "N3EY", "N1KJK"):
            self.assertIn(callsign, callsigns)
        self.assertEqual(sum(row["is_p2p"] for row in rows), 4)
        self.assertEqual(rows[0]["mode"], "SSB")
        self.assertEqual(rows[0]["source_mode"], "PHONE (SSB)")
        self.assertEqual(rows[0]["activation_location"], "US-MN")
        self.assertEqual(rows[0]["park_reference"], "US-11980")
        self.assertEqual(rows[0]["park_name"], "Bethel Wildlife Management Area")

    def test_combined_and_separated_physical_layouts_are_equivalent(self):
        separated, _, _ = parse_pota_activation_contacts(contact_record("N3EY"))
        combined, _, _ = parse_pota_activation_contacts(contact_record("N3EY", combined=True))
        for field in ("worked_callsign", "band", "mode", "activation_location", "park_reference", "park_name"):
            self.assertEqual(separated[0][field], combined[0][field])

    def test_mixed_invalid_records_do_not_shift_into_following_record(self):
        pasted = "\r\n\r\n".join([
            contact_record("K3BAL"),
            contact_record("N3EY").replace("20M", "", 1),
            contact_record("N1KJK", timestamp="2026-99-99 16:39"),
            contact_record("KD3CNZ").replace("US-11980", "", 1),
            contact_record("W1AW"),
        ])
        rows, invalid, _ = parse_pota_activation_contacts(pasted)
        self.assertEqual([row["worked_callsign"] for row in rows], ["K3BAL", "W1AW"])
        self.assertEqual(len(invalid), 3)
        self.assertIn("Band", invalid[0]["reason"])
        self.assertIn("timestamp", invalid[1]["reason"])
        self.assertIn("park reference", invalid[2]["reason"])


class PotaActivationContactWorkflowTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.user = users.objects.create_user("pota-contact-owner", password="test")
        MemberProfile.objects.create(
            user=self.user, callsign="N2JIM", callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.other = users.objects.create_user("pota-contact-other", password="test")
        MemberProfile.objects.create(
            user=self.other, callsign="N0OTHER", callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.adventure = Adventure.objects.create(owner=self.user, title="POTA Contact Destination")
        self.journal = JournalEntry.objects.create(adventure=self.adventure, title="Activation Journal", body="")
        other_adventure = Adventure.objects.create(owner=self.other, title="Private Foreign Adventure")
        self.other_journal = JournalEntry.objects.create(adventure=other_adventure, title="Foreign Journal", body="")
        self.client.force_login(self.user)

    def _preview(self, pasted=None):
        response = self.client.post(reverse("import_pota_contacts"), {
            "adventure": self.adventure.pk, "journal_entry": self.journal.pk,
            "pota_contacts": pasted or contact_record(),
        })
        self.assertEqual(response.status_code, 302)
        return response.url.rsplit("/", 2)[-2]

    def test_menu_labels_and_owned_destinations(self):
        response = self.client.get(reverse("import_pota_contacts"))
        self.assertContains(response, "Import POTA Hunter Contacts")
        self.assertContains(response, "Import POTA Contacts")
        self.assertContains(response, self.adventure.title)
        self.assertContains(response, self.journal.title)
        self.assertNotContains(response, self.other_journal.title)

    def test_preview_is_read_only_and_warns_about_25_of_109(self):
        fixture = (Path(settings.BASE_DIR) / "adventures/test_fixtures/pota_contacts.txt").read_text(encoding="utf-8")
        token = self._preview(fixture)
        self.assertEqual(JournalContact.objects.count(), 0)
        self.assertEqual(PotaImportBatch.objects.count(), 0)
        response = self.client.get(reverse("preview_pota_contacts", args=[token]))
        self.assertContains(response, "This paste contains 25 of 109 contacts shown by POTA. Only the pasted contacts can be imported.")
        self.assertContains(response, "K3BAL")
        self.assertContains(response, "N1KJK")
        self.assertContains(response, "readonly")

    def test_abort_discards_preview_without_writes(self):
        token = self._preview()
        response = self.client.post(reverse("abort_pota_contacts", args=[token]))
        self.assertRedirects(response, reverse("import_pota_contacts"))
        self.assertEqual(JournalContact.objects.count(), 0)
        self.assertEqual(PotaImportBatch.objects.count(), 0)

    def test_forged_destination_and_anonymous_access_are_rejected(self):
        response = self.client.post(reverse("import_pota_contacts"), {
            "adventure": self.other_journal.adventure_id,
            "journal_entry": self.other_journal.pk,
            "pota_contacts": contact_record(),
        })
        self.assertEqual(response.status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("import_pota_contacts")).status_code, 302)

    @patch("adventures.contact_log_views.lookup_callsign")
    def test_selected_rows_import_with_qrz_and_do_not_change_pota_rollups(self, lookup):
        pasted = contact_record("K3BAL") + "\r\n" + contact_record("KD3CNZ", kind="ActivatorP2P")
        token = self._preview(pasted)
        lookup.side_effect = [
            SimpleNamespace(state="PA", country="United States", grid="FN20", latitude="40.0", longitude="-75.0"),
            QRZError("not found"),
        ]
        before_rollups = PotaActivationImport.objects.count()
        response = self.client.post(reverse("confirm_pota_contacts", args=[token]), {"selected": ["0", "1"]})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "POTA Contacts Import Results")
        self.assertContains(response, "Import batch")
        contacts = list(JournalContact.objects.order_by("callsign"))
        self.assertEqual(len(contacts), 2)
        resolved = next(contact for contact in contacts if contact.callsign == "K3BAL")
        unresolved = next(contact for contact in contacts if contact.callsign == "KD3CNZ")
        self.assertEqual((resolved.state, resolved.country, resolved.grid_square), ("PA", "United States", "FN20"))
        self.assertNotEqual(resolved.state, "US-MN")
        self.assertIsNotNone(resolved.latitude)
        self.assertEqual(unresolved.state, "")
        self.assertTrue(unresolved.is_p2p)
        self.assertEqual(PotaActivationImport.objects.count(), before_rollups)
        batch = PotaImportBatch.objects.get()
        self.assertEqual(batch.source, PotaImportBatch.Source.ACTIVATION_CONTACTS)
        self.assertEqual(batch.diagnostics["imported"], 2)

    @patch("adventures.contact_log_views.lookup_callsign")
    def test_existing_and_within_paste_duplicates_are_skipped(self, lookup):
        JournalContact.objects.create(
            journal_entry=self.journal, adventure=self.adventure, owner=self.user,
            qso_date="2026-08-21", time_on=time(16, 39), callsign="K3BAL",
            band="20M", mode="SSB", fingerprint="existing-manual",
        )
        token = self._preview(contact_record("K3BAL") + "\r\n" + contact_record("K3BAL"))
        preview = self.client.get(reverse("preview_pota_contacts", args=[token]))
        self.assertContains(preview, "2 duplicates")
        response = self.client.post(reverse("confirm_pota_contacts", args=[token]), {"selected": ["0", "1"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(JournalContact.objects.count(), 1)
        lookup.assert_not_called()
