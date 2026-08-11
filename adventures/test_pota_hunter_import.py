from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from unittest.mock import patch

from core.models import Adventure, JournalContact, JournalEntry, Location, MemberProfile
from core.pota_test_reset import execute_reset
from .pota_import import group_pota_hunter_qsos, parse_pota_hunter_log


HEADER = "QSO Date\tQSO Time\tStation Callsign\tOperator Callsign\tWorked Callsign\tBand\tMode\tPark Reference\tPark Name\tState/Entity\tQSO ID"


def hunter_row(date, qso_time, park="US-1234", park_name="Pike Lake", worked="K1ABC", band="20M", mode="SSB", qso_id="1", station="W5TEST", operator="W5TEST"):
    return f"{date}\t{qso_time}\t{station}\t{operator}\t{worked}\t{band}\t{mode}\t{park}\t{park_name}\tUS-MN\t{qso_id}"


def screen_record(date="2026-07-31", qso_time="00:02", station="WB0RUR", operator="WB0RUR", worked="W5RIK", band="20M", mode="DATA (FT8)", entity="US-AR", park="US-0721", park_name="Pea Ridge National Military Park"):
    return "\n".join(["Hunter", f"{date} {qso_time}", station, operator, worked, band, mode, entity, park, park_name])


def actual_page_record(date="2026-07-31", qso_time="00:02", station="WB0RUR", operator="WB0RUR", worked="W5RIK", band="20M", mode="DATA (FT8)", entity="US-AR", park="US-0721", park_name="Pea Ridge National Military Park"):
    return "\n".join([f"Hunter\t{date} {qso_time}", station, operator, f"{worked}\t{band}\t{mode}\t{entity}\t{park} {park_name}"])


class PotaHunterParserTests(TestCase):
    def test_direct_screen_copy_single_and_consecutive_records(self):
        text = "\n".join([
            "Hunter Log", "Showing recent contacts",
            screen_record(),
            screen_record(qso_time="00:03", station="KQ4QCT", operator="KQ4QCT", worked="W4ABC", mode="PHONE (SSB)", entity="US-GA", park="US-1049", park_name="Chattahoochee River National Recreation Area"),
        ])
        rows, ignored, invalid = parse_pota_hunter_log(text)
        self.assertEqual((len(rows), invalid), (2, []))
        self.assertEqual(ignored, 2)
        self.assertEqual(rows[0]["mode"], "DATA (FT8)")
        self.assertEqual(rows[1]["mode"], "PHONE (SSB)")
        self.assertEqual(rows[0]["park_name"], "Pea Ridge National Military Park")

    def test_direct_copy_preserves_station_operator_and_international_entities(self):
        text = "\n".join([
            screen_record(station="LZ0A", operator="LZ1AAW", worked="WB0RUR", entity="AQ-SI", park="AQ-0079", park_name="South Shetland Islands Protected Area"),
            screen_record(station="VE6BR", operator="VE6BR", worked="K1ABC", entity="CA-AB", park="CA-3100", park_name="Writing-on-Stone Provincial Park"),
        ])
        rows, _, invalid = parse_pota_hunter_log(text)
        self.assertEqual(invalid, [])
        self.assertEqual((rows[0]["station_callsign"], rows[0]["operator_callsign"]), ("LZ0A", "LZ1AAW"))
        self.assertEqual((rows[0]["entity"], rows[0]["park_reference"]), ("AQ-SI", "AQ-0079"))
        self.assertEqual((rows[1]["entity"], rows[1]["park_reference"]), ("CA-AB", "CA-3100"))

    def test_same_timestamp_multiple_parks_remain_distinct(self):
        text = "\n".join([screen_record(), screen_record(park="US-4424", park_name="Ozark National Forest")])
        rows, _, _ = parse_pota_hunter_log(text)
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["park_reference"] for row in rows}, {"US-0721", "US-4424"})
        self.assertEqual(len(group_pota_hunter_qsos(rows)), 2)

    def test_markdown_style_and_one_line_screen_copy(self):
        pasted = "| Hunter | 2026-07-31 00:02 | W2C | K2EAG | W5RIK | 20M | DATA (MFSK) | US-AR | [US-0721](https://example.test/park) | Pea Ridge National Military Park |"
        rows, _, invalid = parse_pota_hunter_log(pasted)
        self.assertEqual(invalid, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["park_reference"], "US-0721")

    def test_large_direct_copy_block(self):
        rows, ignored, invalid = parse_pota_hunter_log("\n".join(screen_record(qso_time=f"{index // 60:02d}:{index % 60:02d}", park=f"US-{1000 + index:04d}") for index in range(300)))
        self.assertEqual((len(rows), ignored, invalid), (300, 0, []))

    def test_whole_page_copy_ignores_navigation_and_footer(self):
        pasted = "\n".join([
            "Parks on the Air", "Home", "My Hunter Log", "Date Station Operator Worked",
            screen_record(),
            screen_record(qso_time="00:04", station="LZ0A", operator="LZ1AAW", entity="AQ-SI", park="AQ-0079", park_name="South Shetland Islands Protected Area"),
            "Rows per page 25", "Copyright Parks on the Air", "Privacy Policy",
        ])
        rows, ignored, invalid = parse_pota_hunter_log(pasted)
        self.assertEqual((len(rows), invalid), (2, []))
        self.assertEqual(ignored, 7)
        self.assertEqual(rows[-1]["park_name"], "South Shetland Islands Protected Area")

    def test_actual_failing_whole_page_shape_is_reconstructed(self):
        pasted = "\n".join([
            "Parks on the Air", "My Logbook", "Search for Callsigns & Parks",
            "Hunter Log", "Date Range", "Search",
            actual_page_record(),
            actual_page_record(park="US-3791", park_name="Butterfield Trail State Park"),
            "Rows per page", "Copyright Parks on the Air",
        ])
        rows, ignored, invalid = parse_pota_hunter_log(pasted)
        self.assertEqual((len(rows), ignored, invalid), (2, 8, []))
        self.assertEqual(rows[0]["worked_callsign"], "W5RIK")
        self.assertEqual(rows[0]["park_name"], "Pea Ridge National Military Park")
        self.assertEqual(rows[1]["park_reference"], "US-3791")

    def test_csv_remains_supported_and_malformed_block_has_excerpt(self):
        csv_text = HEADER.replace("\t", ",") + "\n" + hunter_row("2026-08-01", "10:00").replace("\t", ",")
        rows, _, invalid = parse_pota_hunter_log(csv_text)
        self.assertEqual((len(rows), invalid), (1, []))
        rows, _, invalid = parse_pota_hunter_log("Hunter\nnot enough fields")
        self.assertEqual(rows, [])
        self.assertIn("not enough fields", invalid[0]["excerpt"])

    def test_parser_and_grouping_combine_qsos_from_one_session(self):
        text = "\n".join([HEADER, hunter_row("2026-08-01", "10:00", qso_id="10"), hunter_row("2026-08-01", "10:15", worked="K2XYZ", mode="CW", qso_id="11")])
        rows, ignored, invalid = parse_pota_hunter_log(text)
        grouped = group_pota_hunter_qsos(rows)
        self.assertEqual((len(rows), ignored, invalid), (2, 1, []))
        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0]["qso_count"], 2)
        self.assertEqual(grouped[0]["bands"], ["20M"])
        self.assertEqual(grouped[0]["modes"], ["CW", "SSB"])
        self.assertEqual(grouped[0]["source_row_ids"], ["10", "11"])

    def test_different_parks_are_separate_and_long_gap_starts_new_session(self):
        text = "\n".join([
            HEADER,
            hunter_row("2026-08-01", "08:00", qso_id="1"),
            hunter_row("2026-08-01", "13:01", qso_id="2"),
            hunter_row("2026-08-01", "09:00", park="US-9999", park_name="Other Park", qso_id="3"),
        ])
        rows, _, _ = parse_pota_hunter_log(text)
        grouped = group_pota_hunter_qsos(rows, session_gap=timedelta(hours=4))
        self.assertEqual(len(grouped), 3)


@override_settings(GOOGLE_GEOCODING_API_KEY="", POTA_PARK_REFERENCE_DATA={
    "US-1234": {"name": "Pike Lake", "entity": "US-MN", "latitude": "46.123456", "longitude": "-92.654321"},
})
class PotaHunterImportWorkflowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="W5TEST", password="password")
        MemberProfile.objects.create(user=self.user, callsign="W5TEST", callsign_verified=True, verification_method=MemberProfile.VerificationMethod.QRZ)
        self.adventure = Adventure.objects.create(owner=self.user, title="Hunter Destination")
        self.journal = JournalEntry.objects.create(adventure=self.adventure, title="Hunter Journal", body="")
        self.client.force_login(self.user)

    def _preview(self, rows):
        response = self.client.post(reverse("import_pota_hunter_log"), {
            "adventure": self.adventure.pk, "journal_entry": self.journal.pk,
            "pota_hunter_log": "\n".join([HEADER, *rows]),
        })
        self.assertEqual(response.status_code, 302)
        return response.url

    def test_contact_log_is_the_hunter_entry_point(self):
        hunter_url = reverse("import_pota_hunter_log")
        self.assertEqual(hunter_url, "/adventures/contacts/import/pota-hunter/")
        contact_log = self.client.get(reverse("my_contact_log"))
        self.assertContains(contact_log, "My Contact Log")
        self.assertContains(contact_log, f'href="{hunter_url}"')
        my_adventures = self.client.get(reverse("my_adventures"))
        self.assertContains(my_adventures, "Import POTA Hunter Log")
        self.assertContains(my_adventures, f'href="{hunter_url}"')
        hunter_start = self.client.get(hunter_url)
        self.assertContains(hunter_start, "Destination Adventure")
        self.assertContains(hunter_start, f'href="{reverse("import_pota_history")}"')
        history_start = self.client.get(reverse("import_pota_history"))
        self.assertContains(history_start, f'href="{hunter_url}"')
        preview = self.client.get(self._preview([hunter_row("2026-08-01", "10:00"), hunter_row("2026-08-01", "10:20", qso_id="2")]))
        self.assertContains(preview, "Preview Contacts")
        self.assertContains(preview, "2 recognized")
        self.assertContains(preview, "Import Selected Contacts", count=2)
        self.assertEqual(Adventure.objects.count(), 1)

    def test_direct_screen_paste_reaches_preview_with_parsed_qso_fields(self):
        pasted = "\n".join([
            screen_record(station="W5TEST", operator="W8DF", worked="KB9IAR"),
            screen_record(qso_time="00:04", station="W5TEST", operator="W5TEST", worked="KQ4QCT", park="US-1049", park_name="Chattahoochee River National Recreation Area"),
        ])
        response = self.client.post(reverse("import_pota_hunter_log"), {"adventure": self.adventure.pk, "journal_entry": self.journal.pk, "pota_hunter_log": pasted})
        self.assertEqual(response.status_code, 302)
        preview = self.client.get(response.url)
        self.assertContains(preview, "2 recognized; 0 imported; 0 duplicates; 0 ignored; 0 invalid")
        for value in ("W5TEST", "W8DF", "KB9IAR", "DATA (FT8)", "US-AR", "US-0721", "Pea Ridge National Military Park"):
            self.assertContains(preview, value)

    def test_actual_whole_page_paste_previews_and_imports_contacts_only(self):
        pasted = "\n".join([
            "Parks on the Air", "My Logbook", "Hunter Log", "Date Range", "Search",
            actual_page_record(station="W5TEST", operator="W8DF", worked="KB9IAR"),
            "Privacy", "Copyright",
        ])
        response = self.client.post(reverse("import_pota_hunter_log"), {"adventure": self.adventure.pk, "journal_entry": self.journal.pk, "pota_hunter_log": pasted})
        self.assertEqual(response.status_code, 302)
        preview = self.client.get(response.url)
        self.assertContains(preview, "1 recognized")
        token = response.url.rstrip("/").split("/")[-1]
        imported = self.client.post(reverse("confirm_pota_hunter_log", args=[token]), {"selected": ["0"]})
        self.assertRedirects(imported, reverse("journal_entry_detail", args=[self.journal.pk]))
        self.assertEqual(JournalContact.objects.filter(source=JournalContact.Source.POTA_HUNTER).count(), 1)
        self.assertEqual(Adventure.objects.count(), 1)
        self.assertEqual(Location.objects.count(), 0)

    def test_malformed_submission_shows_sanitized_excerpt(self):
        response = self.client.post(reverse("import_pota_hunter_log"), {"adventure": self.adventure.pk, "journal_entry": self.journal.pk, "pota_hunter_log": "unrelated heading\nno Hunter records here"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "First unrecognized excerpt")
        self.assertContains(response, "No Hunter record boundary")

    def test_visitor_and_unverified_member_do_not_get_hunter_entry_points(self):
        self.client.logout()
        home = self.client.get(reverse("home"))
        self.assertNotContains(home, "Import POTA Hunter Log")
        direct = self.client.get(reverse("import_pota_hunter_log"))
        self.assertEqual(direct.status_code, 302)

        pending = get_user_model().objects.create_user(username="N0PEND", password="password")
        MemberProfile.objects.create(user=pending, callsign="N0PEND", callsign_verified=False)
        self.client.force_login(pending)
        self.assertNotContains(self.client.get(reverse("home")), "Import POTA Hunter Log")
        self.assertEqual(self.client.get(reverse("import_pota_hunter_log")).status_code, 403)

    def test_selected_rows_create_journal_and_adventure_associated_contacts(self):
        preview_url = self._preview([hunter_row("2026-08-01", "10:00", qso_id="73"), hunter_row("2026-08-01", "10:20", mode="CW", qso_id="74")])
        token = preview_url.rstrip("/").split("/")[-1]
        response = self.client.post(reverse("confirm_pota_hunter_log", args=[token]), {"selected": ["0", "1"]})
        self.assertRedirects(response, reverse("journal_entry_detail", args=[self.journal.pk]))
        self.assertEqual(Adventure.objects.count(), 1)
        self.assertEqual(Location.objects.count(), 0)
        contacts = list(JournalContact.objects.order_by("time_on"))
        self.assertEqual(len(contacts), 2)
        self.assertTrue(all(contact.source == JournalContact.Source.POTA_HUNTER for contact in contacts))
        self.assertTrue(all(contact.owner == self.user and contact.adventure == self.adventure and contact.journal_entry == self.journal for contact in contacts))

    def test_journal_launch_imports_into_unified_log_and_parent_adventure(self):
        adventure = Adventure.objects.create(owner=self.user, title="Journal-owned QSOs")
        journal = JournalEntry.objects.create(adventure=adventure, title="Saturday", body="")
        start = self.client.get(
            reverse("import_pota_hunter_log"), {"journal_entry": journal.pk}
        )
        self.assertContains(start, "Journal-owned QSOs")
        response = self.client.post(reverse("import_pota_hunter_log"), {
            "journal_entry": journal.pk,
            "pota_hunter_log": "\n".join([HEADER, hunter_row("2026-08-01", "10:00")]),
        })
        token = response.url.rstrip("/").split("/")[-1]
        preview = self.client.get(response.url)
        self.assertContains(preview, "Saturday")
        imported = self.client.post(reverse("confirm_pota_hunter_log", args=[token]), {
            "journal_entry": journal.pk,
            "selected": ["0"],
        })
        self.assertRedirects(imported, reverse("journal_entry_detail", args=[journal.pk]))
        contact = JournalContact.objects.get()
        self.assertEqual(contact.journal_entry, journal)
        self.assertEqual(contact.adventure, adventure)
        self.assertEqual(contact.source, JournalContact.Source.POTA_HUNTER)
        self.assertEqual(Adventure.objects.count(), 2)
        self.assertEqual(JournalEntry.objects.count(), 2)
        self.assertEqual(Location.objects.count(), 0)
        self.assertContains(self.client.get(reverse("my_contact_log")), "Saturday")
        self.assertContains(self.client.get(reverse("adventure_contacts", args=[adventure.slug])), "K1ABC")

    def test_global_import_requires_matching_adventure_and_journal(self):
        other_adventure = Adventure.objects.create(owner=self.user, title="Other Adventure")
        response = self.client.post(reverse("import_pota_hunter_log"), {
            "adventure": other_adventure.pk,
            "journal_entry": self.journal.pk,
            "pota_hunter_log": "\n".join([HEADER, hunter_row("2026-08-01", "10:00")]),
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "does not belong to the selected Adventure")
        self.assertEqual(JournalContact.objects.count(), 0)

        response = self.client.post(reverse("import_pota_hunter_log"), {
            "adventure": self.adventure.pk,
            "pota_hunter_log": "\n".join([HEADER, hunter_row("2026-08-01", "10:00")]),
        })
        self.assertContains(response, "Select a destination Journal")
        self.assertEqual(JournalContact.objects.count(), 0)

    def test_preview_destination_survives_confirm_without_posted_journal(self):
        preview_url = self._preview([hunter_row("2026-08-01", "10:00")])
        token = preview_url.rstrip("/").split("/")[-1]
        other_adventure = Adventure.objects.create(owner=self.user, title="Other")
        other_journal = JournalEntry.objects.create(adventure=other_adventure, title="Other Journal", body="")
        response = self.client.post(reverse("confirm_pota_hunter_log", args=[token]), {
            "journal_entry": other_journal.pk,
            "selected": ["0"],
        })
        self.assertRedirects(response, reverse("journal_entry_detail", args=[self.journal.pk]))
        contact = JournalContact.objects.get()
        self.assertEqual(contact.journal_entry, self.journal)
        self.assertEqual(contact.adventure, self.adventure)

    def test_contact_journal_synchronizes_adventure_and_rejects_mismatch(self):
        first = Adventure.objects.create(owner=self.user, title="First")
        second = Adventure.objects.create(owner=self.user, title="Second")
        journal = JournalEntry.objects.create(adventure=first, title="Session", body="")
        contact = JournalContact(
            owner=self.user, journal_entry=journal, adventure=second,
            qso_date="2026-08-01", callsign="K1SYNC", fingerprint="sync-contact",
        )
        with self.assertRaisesMessage(ValidationError, "must match"):
            contact.full_clean()
        contact.save()
        self.assertEqual(contact.adventure, first)

    def test_reimport_is_duplicate(self):
        rows = [hunter_row("2026-08-01", "10:00")]
        preview_url = self._preview(rows)
        token = preview_url.rstrip("/").split("/")[-1]
        self.client.post(reverse("confirm_pota_hunter_log", args=[token]), {"selected": ["0"]})
        second = self.client.get(self._preview(rows))
        self.assertContains(second, "Duplicate")
        self.assertEqual(JournalContact.objects.count(), 1)

    @override_settings(DEBUG=True)
    @patch("core.pota_test_reset.create_database_backup", return_value="test-backup.sqlite3")
    def test_reset_makes_deleted_hunter_contact_importable_again(self, backup):
        rows = [hunter_row("2026-08-01", "10:00")]
        first_url = self._preview(rows)
        first_token = first_url.rstrip("/").split("/")[-1]
        self.client.post(reverse("confirm_pota_hunter_log", args=[first_token]), {"selected": ["0"]})
        self.assertContains(self.client.get(self._preview(rows)), "Duplicate")
        execute_reset(allow_test_database=True)
        ready = self.client.get(self._preview(rows))
        self.assertContains(ready, "Ready")
        token = ready.request["PATH_INFO"].rstrip("/").split("/")[-1]
        self.client.post(reverse("confirm_pota_hunter_log", args=[token]), {"selected": ["0"]})
        self.assertEqual(JournalContact.objects.filter(source=JournalContact.Source.POTA_HUNTER).count(), 1)

    def test_station_operator_difference_and_multi_park_rows_are_preserved(self):
        preview_url = self._preview([
            hunter_row("2026-08-01", "10:00", station="W2C", operator="K2EAG", park="US-1234"),
            hunter_row("2026-08-01", "10:00", station="W2C", operator="K2EAG", park="US-9999", park_name="Other Park"),
        ])
        token = preview_url.rstrip("/").split("/")[-1]
        self.client.post(reverse("confirm_pota_hunter_log", args=[token]), {"selected": ["0", "1"]})
        self.assertEqual(JournalContact.objects.count(), 2)
        self.assertEqual(set(JournalContact.objects.values_list("pota_park_reference", flat=True)), {"US-1234", "US-9999"})
        self.assertEqual(JournalContact.objects.first().operator_callsign, "K2EAG")

    def test_another_user_cannot_open_preview(self):
        preview_url = self._preview([hunter_row("2026-08-01", "10:00")])
        other = get_user_model().objects.create_user(username="N0OTHER", password="password")
        MemberProfile.objects.create(user=other, callsign="N0OTHER", callsign_verified=True, verification_method=MemberProfile.VerificationMethod.QRZ)
        self.client.force_login(other)
        response = self.client.get(preview_url)
        self.assertRedirects(response, reverse("import_pota_hunter_log"))

    def test_contact_log_is_private_and_includes_existing_adventure_contact(self):
        adventure = Adventure.objects.create(owner=self.user, title="Field Day")
        journal = JournalEntry.objects.create(adventure=adventure, title="Operating", body="")
        manual = JournalContact.objects.create(journal_entry=journal, owner=self.user, qso_date="2026-08-01", callsign="K1MAN", fingerprint="manual-contact", source=JournalContact.Source.MANUAL)
        other = get_user_model().objects.create_user(username="N0PRIVATE")
        private = JournalContact.objects.create(owner=other, qso_date="2026-08-01", callsign="K1HIDDEN", fingerprint="private-contact")
        response = self.client.get(reverse("my_contact_log"))
        self.assertContains(response, "K1MAN")
        self.assertContains(response, "Field Day")
        self.assertNotContains(response, "K1HIDDEN")
        self.assertEqual(manual.journal_entry, journal)
        self.assertIsNone(private.adventure)
