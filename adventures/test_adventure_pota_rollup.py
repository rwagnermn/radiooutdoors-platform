from datetime import date

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core.models import (
    Adventure,
    JournalContact,
    JournalEntry,
    MemberProfile,
    PotaActivationImport,
    PotaImportBatch,
)


class AdventurePotaRollupTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user("rollup-owner", password="test")
        MemberProfile.objects.create(
            user=self.owner,
            callsign="W5ROLL",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.adventure = Adventure.objects.create(
            owner=self.owner, title="Roll-Up Adventure", is_public=True
        )
        self.batch = PotaImportBatch.objects.create(owner=self.owner)

    def journal(self, title, counts=None, adventure=None):
        adventure = adventure or self.adventure
        journal = JournalEntry.objects.create(
            adventure=adventure,
            title=title,
            body="Journal",
            is_public=True,
            pota=True,
        )
        if counts is not None:
            index = PotaActivationImport.objects.count() + 1
            PotaActivationImport.objects.create(
                adventure=adventure,
                journal_entry=journal,
                batch=self.batch,
                activation_date=date(2026, 8, min(index, 28)),
                callsign="W5ROLL",
                park_reference=f"US-{index:04d}",
                park_name=title,
                cw_contacts=counts[0],
                data_contacts=counts[1],
                phone_contacts=counts[2],
                total_contacts=counts[3],
                fingerprint=f"rollup-{adventure.pk}-{journal.pk}",
                location_resolution="existing",
            )
        return journal

    def detail(self, adventure=None):
        adventure = adventure or self.adventure
        return self.client.get(reverse("adventure_detail", args=[adventure.slug]))

    def test_rollup_placement_and_view_contacts_link(self):
        journal = self.journal("Contact Journal", (1, 2, 3, 6))
        JournalContact.objects.create(
            journal_entry=journal,
            qso_date=date(2026, 8, 14),
            callsign="K1ABC",
            fingerprint="rollup-contact",
        )
        response = self.detail()
        content = response.content.decode()
        heading = content.index("QSO’s and Contacts")
        rollup = content.index("POTA Roll-Up")
        first_contact = content.index("K1ABC")
        self.assertLess(heading, rollup)
        self.assertLess(rollup, first_contact)
        self.assertContains(response, "View Contacts")

    def test_preview_headers_are_screen_reader_only_while_full_page_headers_remain_visible(self):
        journal = self.journal("Accessible Contact Journal", (1, 2, 3, 6))
        JournalContact.objects.create(
            journal_entry=journal,
            qso_date=date(2026, 8, 14),
            callsign="K1A11Y",
            fingerprint="rollup-accessible-contact",
        )

        preview = self.detail()
        self.assertContains(preview, '<thead class="visually-hidden">', html=False)
        for label in ("Date", "Callsign", "Band", "Mode", "State", "Country"):
            self.assertContains(preview, f'<th scope="col">{label}</th>', html=False)

        full_page = self.client.get(
            reverse("adventure_contacts", args=[self.adventure.slug])
        )
        self.assertEqual(full_page.status_code, 200)
        self.assertContains(full_page, "<thead><tr>", html=False)
        self.assertNotContains(full_page, '<thead class="visually-hidden">', html=False)

    def test_one_and_multiple_journals_derive_totals_and_exclude_other_adventure(self):
        self.journal("First", (2, 5, 10, 19))
        one = self.detail()
        self.assertEqual(one.context["pota_rollup"], {"cw": 2, "data": 5, "phone": 10, "total": 17})
        self.journal("Second", (3, 7, 11, 25))
        other = Adventure.objects.create(owner=self.owner, title="Other Roll-Up")
        self.journal("Foreign", (9999, 9999, 9999, 99999), adventure=other)
        multiple = self.detail()
        self.assertEqual(multiple.context["pota_rollup"], {"cw": 5, "data": 12, "phone": 21, "total": 38})

    def test_missing_values_and_empty_adventures_display_zero(self):
        empty = self.detail()
        self.assertEqual(empty.context["pota_rollup"], {"cw": 0, "data": 0, "phone": 0, "total": 0})
        self.journal("No POTA aggregate")
        no_import = self.detail()
        self.assertEqual(no_import.context["pota_rollup"], {"cw": 0, "data": 0, "phone": 0, "total": 0})
        for label in ("POTA Roll-Up", "CW", "DATA", "PHONE", "TOTAL"):
            self.assertContains(no_import, label)

    def test_total_is_derived_and_large_values_are_not_truncated(self):
        self.journal("Large", (9999, 9999, 9999, 99999))
        response = self.detail()
        self.assertEqual(response.context["pota_rollup"]["total"], 29997)
        self.assertContains(response, "29997")
        self.assertNotEqual(response.context["pota_rollup"]["total"], 99999)

    def test_rollup_uses_one_aggregate_query_without_per_journal_fetches(self):
        for index in range(5):
            self.journal(f"Journal {index}", (index, index, index, index))
        with CaptureQueriesContext(connection) as queries:
            response = self.detail()
        self.assertEqual(response.status_code, 200)
        rollup_queries = [
            query["sql"] for query in queries.captured_queries
            if "SUM(" in query["sql"].upper() and "core_potaactivationimport" in query["sql"]
        ]
        self.assertEqual(len(rollup_queries), 1)

    def test_private_adventure_authorization_is_unchanged(self):
        self.adventure.is_public = False
        self.adventure.save(update_fields=["is_public"])
        self.assertEqual(self.detail().status_code, 404)
        self.client.force_login(self.owner)
        self.assertEqual(self.detail().status_code, 200)
