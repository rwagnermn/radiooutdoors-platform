from datetime import timedelta
import json

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


def p2p_screen_record(**kwargs):
    return screen_record(**kwargs).replace("Hunter\n", "Hunter\nP2P\n", 1)


def hunterp2p_record(**kwargs):
    return screen_record(**kwargs).replace("Hunter\n", "HunterP2P\n", 1)


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

    def test_p2p_badge_does_not_shift_hunter_fields(self):
        rows, ignored, invalid = parse_pota_hunter_log("\n".join([
            screen_record(worked="W5NORMAL"),
            p2p_screen_record(qso_time="00:03", station="W2C", operator="K2EAG", worked="W5P2P", park="US-9935", park_name="Virginia Bird & Wildlife State Trail"),
        ]))
        self.assertEqual((len(rows), ignored, invalid), (2, 0, []))
        self.assertFalse(rows[0]["is_p2p"])
        self.assertTrue(rows[1]["is_p2p"])
        self.assertEqual(rows[1]["qso_at"].strftime("%Y-%m-%d %H:%M"), "2026-07-31 00:03")
        self.assertEqual((rows[1]["station_callsign"], rows[1]["operator_callsign"], rows[1]["worked_callsign"]), ("W2C", "K2EAG", "W5P2P"))
        self.assertEqual((rows[1]["park_reference"], rows[1]["park_name"]), ("US-9935", "Virginia Bird & Wildlife State Trail"))

    def test_inline_p2p_whole_page_shape_parses(self):
        pasted = actual_page_record().replace("Hunter\t", "Hunter\tP2P\t", 1)
        rows, _, invalid = parse_pota_hunter_log(pasted)
        self.assertEqual((len(rows), invalid), (1, []))
        self.assertTrue(rows[0]["is_p2p"])

    def test_hunterp2p_row_type_and_normal_rows_coexist_without_field_shift(self):
        pasted = "\n".join([
            hunterp2p_record(date="2025-06-04", qso_time="18:30", station="AA8HF", operator="AA8HF", worked="W5RIK", band="20M", mode="PHONE (SSB)", entity="US-MI", park="US-1518", park_name="Maybury State Park"),
            hunterp2p_record(date="2025-06-04", qso_time="18:25", station="KB9JMU", operator="KB9JMU", worked="W5RIK", band="20M", mode="PHONE (SSB)", entity="US-KY", park="US-0019", park_name="Cumberland Gap National Historical Park"),
            hunterp2p_record(date="2025-06-04", qso_time="18:21", station="K8NEE", operator="K8NEE", worked="W5RIK", band="20M", mode="PHONE (SSB)", entity="US-SC", park="US-4577", park_name="Overmountain Victory National Historic Trail"),
            screen_record(date="2025-05-03", qso_time="17:50", station="VA3GHB", operator="VA3GHB", worked="W5RIK", band="20M", mode="DATA (FT8)", entity="CA-ON", park="CA-1525", park_name="Morningside Park"),
        ])
        rows, ignored, invalid = parse_pota_hunter_log(pasted)
        self.assertEqual((len(rows), ignored, invalid), (4, 0, []))
        first = rows[0]
        self.assertTrue(first["is_p2p"])
        self.assertEqual(first["qso_at"].strftime("%Y-%m-%d %H:%M"), "2025-06-04 18:30")
        self.assertEqual((first["station_callsign"], first["operator_callsign"], first["worked_callsign"]), ("AA8HF", "AA8HF", "W5RIK"))
        self.assertEqual((first["band"], first["mode"], first["entity"]), ("20M", "PHONE (SSB)", "US-MI"))
        self.assertEqual((first["park_reference"], first["park_name"]), ("US-1518", "Maybury State Park"))
        self.assertFalse(rows[-1]["is_p2p"])

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
        self.assertContains(my_adventures, "Import POTA Contacts", count=1)
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
        self.assertContains(preview, "2 recognized; 0 imported; 0 duplicates; 2 No Pin; 0 ignored; 0 invalid")
        for value in ("W5TEST", "W8DF", "KB9IAR", "DATA (FT8)", "US-AR", "US-0721", "Pea Ridge National Military Park"):
            self.assertContains(preview, value)

    def test_hunterp2p_row_type_previews_and_imports_as_p2p_contact(self):
        pasted = "\n".join([
            hunterp2p_record(date="2025-06-04", qso_time="18:30", station="AA8HF", operator="AA8HF", worked="W5RIK", mode="PHONE (SSB)", park="US-1518", park_name="Maybury State Park"),
            screen_record(date="2025-05-03", qso_time="17:50", station="VA3GHB", operator="VA3GHB", worked="W5RIK", entity="CA-ON", park="CA-1525", park_name="Morningside Park"),
        ])
        response = self.client.post(reverse("import_pota_hunter_log"), {
            "adventure": self.adventure.pk, "journal_entry": self.journal.pk,
            "pota_hunter_log": pasted,
        })
        preview = self.client.get(response.url)
        self.assertContains(preview, "2 recognized")
        self.assertContains(preview, 'class="pota-p2p-badge">P2P</span>', count=1)
        self.assertContains(preview, '<small class="pota-p2p-secondary"><span class="pota-p2p-badge">P2P</span></small>', count=1)
        self.assertContains(preview, 'type="checkbox" name="selected"', count=2)
        token = response.url.rstrip("/").split("/")[-1]
        self.client.post(reverse("confirm_pota_hunter_log", args=[token]), {"selected": ["all"]})
        self.assertEqual(JournalContact.objects.count(), 2)
        p2p = JournalContact.objects.get(station_callsign="AA8HF")
        self.assertTrue(p2p.is_p2p)
        self.assertEqual((p2p.callsign, p2p.band, p2p.mode, p2p.pota_park_reference, p2p.pota_park_name), ("W5RIK", "20M", "PHONE", "US-1518", "Maybury State Park"))

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
        self.assertEqual(Location.objects.count(), 1)
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
        self.assertEqual(Location.objects.count(), 1)
        self.assertContains(self.client.get(reverse("my_contact_log")), "Saturday")
        self.assertContains(self.client.get(reverse("adventure_contacts", args=[adventure.slug])), "K1ABC")

    def test_global_import_rejects_mismatch_but_allows_unassigned_contacts(self):
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
            "pota_hunter_log": "\n".join([HEADER, hunter_row("2026-08-01", "10:00")]),
        })
        token = response.url.rstrip("/").split("/")[-1]
        imported = self.client.post(reverse("confirm_pota_hunter_log", args=[token]), {"selected": ["0"]})
        self.assertRedirects(imported, reverse("my_contact_log"))
        contact = JournalContact.objects.get()
        self.assertIsNone(contact.journal_entry)
        self.assertIsNone(contact.adventure)

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

    def test_hunter_fields_and_configured_park_location_are_preserved(self):
        before_adventures = Adventure.objects.count()
        before_journals = JournalEntry.objects.count()
        preview_url = self._preview([hunter_row(
            "2026-08-01", "10:17", station="W2C", operator="K2EAG",
            worked="W5RIK", band="20M", mode="DATA (FT8)",
            park="US-1234", park_name="US-1234 Pike Lake",
        )])
        token = preview_url.rstrip("/").split("/")[-1]
        self.client.post(reverse("confirm_pota_hunter_log", args=[token]), {"selected": ["0"]})
        contact = JournalContact.objects.get()
        self.assertEqual(contact.station_callsign, "W2C")
        self.assertEqual(contact.operator_callsign, "K2EAG")
        self.assertEqual(contact.callsign, "W5RIK")
        self.assertEqual((contact.band, contact.mode, contact.submode), ("20M", "DATA", "FT8"))
        self.assertEqual(contact.state, "US-MN")
        self.assertEqual(contact.pota_park_reference, "US-1234")
        self.assertEqual(contact.pota_park_name, "Pike Lake")
        self.assertEqual(contact.source, JournalContact.Source.POTA_HUNTER)
        self.assertEqual(contact.resolved_location.reference_code, "US-1234")
        self.assertEqual(str(contact.resolved_location.latitude), "46.123456")
        self.assertEqual(str(contact.resolved_location.longitude), "-92.654321")
        self.assertEqual(Adventure.objects.count(), before_adventures)
        self.assertEqual(JournalEntry.objects.count(), before_journals)

    def test_journal_contact_table_renders_compact_fields_and_owner_action(self):
        token = self._preview([hunter_row(
            "2026-08-01", "10:17", station="W2C", operator="K2EAG",
            worked="W5RIK", band="20M", mode="DATA (FT8)",
            park="US-1234", park_name="Pike Lake",
        )]).rstrip("/").split("/")[-1]
        self.client.post(reverse("confirm_pota_hunter_log", args=[token]), {"selected": ["0"]})
        contact = JournalContact.objects.get()
        response = self.client.get(reverse("journal_entry_detail", args=[self.journal.pk]))
        for heading in ("Date", "Callsign", "Band", "Mode", "Location"):
            self.assertContains(response, f">{heading}<")
        for heading in ("Station", "Operator", "Worked", "Park", "Source", "Actions"):
            self.assertNotContains(response, f">{heading}<")
        for value in ("W5RIK", "20M", "DATA (FT8)", "US-MN"):
            self.assertContains(response, value)
        self.assertContains(response, f'aria-label="Actions for Contact {contact.callsign}"')
        self.assertContains(response, reverse("delete_journal_contact", args=[self.journal.pk, contact.pk]))

    def test_journal_contact_actions_are_hidden_from_unauthorized_viewer(self):
        contact = JournalContact.objects.create(
            owner=self.user, journal_entry=self.journal, qso_date="2026-08-01",
            callsign="K1PUBLIC", fingerprint="public-journal-contact",
        )
        self.adventure.is_public = True
        self.adventure.save(update_fields=["is_public"])
        self.journal.is_public = True
        self.journal.save(update_fields=["is_public"])
        other = get_user_model().objects.create_user(username="N0VIEW", password="password")
        MemberProfile.objects.create(user=other, callsign="N0VIEW", callsign_verified=True, verification_method=MemberProfile.VerificationMethod.QRZ)
        self.client.force_login(other)
        response = self.client.get(reverse("journal_entry_detail", args=[self.journal.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("delete_journal_contact", args=[self.journal.pk, contact.pk]))
        denied = self.client.post(reverse("delete_journal_contact", args=[self.journal.pk, contact.pk]))
        self.assertEqual(denied.status_code, 403)
        self.assertTrue(JournalContact.objects.filter(pk=contact.pk).exists())

    def test_manual_contact_missing_optional_fields_renders_safely(self):
        JournalContact.objects.create(
            owner=self.user, journal_entry=self.journal, qso_date="2026-08-01",
            callsign="K1MANUAL", fingerprint="manual-safe-display",
            source=JournalContact.Source.MANUAL,
        )
        response = self.client.get(reverse("journal_entry_detail", args=[self.journal.pk]))
        self.assertContains(response, "K1MANUAL")
        self.assertContains(response, "—")

    def test_existing_reference_location_is_reused_without_duplicate(self):
        existing = Location.objects.create(
            name="Existing Pike Lake", reference_code="us-1234", state="MN",
            latitude="46.100000", longitude="-92.600000",
        )
        token = self._preview([hunter_row("2026-08-01", "10:00")]).rstrip("/").split("/")[-1]
        self.client.post(reverse("confirm_pota_hunter_log", args=[token]), {"selected": ["0"]})
        self.assertEqual(Location.objects.count(), 1)
        self.assertEqual(JournalContact.objects.get().resolved_location, existing)

    def test_name_and_state_match_is_preferred_over_reference_only_match(self):
        reference_only = Location.objects.create(
            name="Different Place", reference_code="US-1234", state="WI",
            latitude="44.000000", longitude="-89.000000",
        )
        name_match = Location.objects.create(
            name="Pike Lake", reference_code="", state="MN",
            latitude="46.100000", longitude="-92.600000",
        )
        token = self._preview([hunter_row("2026-08-01", "10:00")]).rstrip("/").split("/")[-1]
        self.client.post(reverse("confirm_pota_hunter_log", args=[token]), {"selected": ["0"]})
        self.assertEqual(JournalContact.objects.get().resolved_location, name_match)
        self.assertNotEqual(JournalContact.objects.get().resolved_location, reference_only)

    @override_settings(POTA_PARK_REFERENCE_DATA={}, GOOGLE_GEOCODING_API_KEY="test-key")
    @patch("adventures.pota_geocoding.urlopen")
    def test_nearby_different_name_geocode_in_state_creates_location_and_distance(self, mocked_open):
        response = mocked_open.return_value.__enter__.return_value
        response.read.return_value = json.dumps({"status": "OK", "results": [{
            "formatted_address": "Garfield Public Use Area, Garfield, AR, USA",
            "types": ["park", "point_of_interest"],
            "geometry": {"location": {"lat": 36.454, "lng": -94.034}},
            "address_components": [
                {"short_name": "AR", "types": ["administrative_area_level_1"]},
                {"short_name": "US", "types": ["country"]},
            ],
        }]}).encode()
        origin = Location.objects.create(
            name="Home Park", state="AR", latitude="35.000000", longitude="-93.000000"
        )
        self.adventure.location = origin
        self.adventure.save(update_fields=["location"])
        token = self._preview([hunter_row(
            "2026-08-01", "10:00", park="US-0721",
            park_name="US-0721 Pea Ridge National Military Park",
        ).replace("US-MN", "US-AR")]).rstrip("/").split("/")[-1]
        self.client.post(reverse("confirm_pota_hunter_log", args=[token]), {"selected": ["0"]})
        contact = JournalContact.objects.get()
        self.assertEqual(contact.pota_park_name, "Pea Ridge National Military Park")
        self.assertEqual(contact.resolved_location.reference_code, "US-0721")
        self.assertEqual(str(contact.resolved_location.latitude), "36.454000")
        self.assertGreater(contact.distance_miles, 0)
        self.assertIn("Provider suggestion: Garfield Public Use Area", contact.resolved_location.description)
        requested_url = mocked_open.call_args.args[0]
        self.assertIn("Pea+Ridge+National+Military+Park%2C+Arkansas%2C+United+States", requested_url)

    @override_settings(POTA_PARK_REFERENCE_DATA={}, GOOGLE_GEOCODING_API_KEY="")
    def test_failed_location_lookup_does_not_block_contact_import(self):
        token = self._preview([hunter_row("2026-08-01", "10:00", park="US-9999", park_name="Unknown Park")]).rstrip("/").split("/")[-1]
        self.client.post(reverse("confirm_pota_hunter_log", args=[token]), {"selected": ["0"]})
        contact = JournalContact.objects.get()
        self.assertIsNone(contact.resolved_location)
        self.assertEqual(contact.pota_park_name, "Unknown Park")
        self.assertEqual(Location.objects.count(), 0)

    @override_settings(POTA_PARK_REFERENCE_DATA={}, GOOGLE_GEOCODING_API_KEY="")
    def test_nine_valid_rows_survive_six_location_failures_and_reimport_as_duplicates(self):
        source_rows = [
            (screen_record if index < 3 else p2p_screen_record)(
                qso_time=f"00:{index:02d}", worked=f"W5R{index:02d}",
                park=f"US-{9900 + index}", park_name=f"Hunter Park {index}",
            )
            for index in range(9)
        ]
        parsed, ignored, invalid = parse_pota_hunter_log("\n".join(source_rows))
        self.assertEqual((len(parsed), ignored, invalid), (9, 0, []))

        pinned = {}
        for index in range(3):
            reference = f"US-{9900 + index}"
            pinned[reference] = Location.objects.create(
                name=f"Hunter Park {index}", reference_code=reference,
                state="AR", latitude=f"36.{index}00000", longitude="-94.000000",
            )
        parks = [
            {
                "reference": f"US-{9900 + index}", "name": f"Hunter Park {index}",
                "entity": "US-AR", "matched_location_id": pinned.get(f"US-{9900 + index}").pk if index < 3 else None,
                "latitude": f"36.{index}00000" if index < 3 else "",
                "longitude": "-94.000000" if index < 3 else "",
            }
            for index in range(9)
        ]
        with patch("adventures.contact_log_views._unique_parks", return_value=parks):
            response = self.client.post(reverse("import_pota_hunter_log"), {
                "adventure": self.adventure.pk, "journal_entry": self.journal.pk,
                "pota_hunter_log": "\n".join(source_rows),
            })
        token = response.url.rstrip("/").split("/")[-1]
        preview = self.client.get(response.url)
        self.assertContains(preview, "9 recognized")
        self.assertContains(preview, "6 No Pin")
        self.assertContains(preview, "Ready — No Pin", count=6)
        self.assertContains(preview, 'class="pota-p2p-badge">P2P</span>', count=6)
        self.assertContains(preview, 'type="checkbox" name="selected"', count=9)

        with patch("adventures.contact_log_views._resolve_hunter_locations", return_value={
            f"US-{9900 + index}": pinned.get(f"US-{9900 + index}") for index in range(9)
        }):
            imported = self.client.post(reverse("confirm_pota_hunter_log", args=[token]), {"selected": ["all"]})
        self.assertEqual(JournalContact.objects.count(), 9)
        self.assertEqual(JournalContact.objects.filter(resolved_location__isnull=False).count(), 3)
        self.assertEqual(JournalContact.objects.filter(resolved_location__isnull=True, distance_miles__isnull=True).count(), 6)
        self.assertEqual(JournalContact.objects.filter(is_p2p=True).count(), 6)
        unresolved = JournalContact.objects.get(pota_park_reference="US-9908")
        self.assertEqual(unresolved.pota_park_name, "Hunter Park 8")
        self.assertIsNone(unresolved.latitude)
        self.assertIsNone(unresolved.longitude)
        journal_detail = self.client.get(reverse("journal_entry_detail", args=[self.journal.pk]))
        self.assertContains(journal_detail, "QSO’s and Contacts")
        self.assertContains(journal_detail, "9 total")
        adventure_contacts = self.client.get(reverse("adventure_contacts", args=[self.adventure.slug]))
        self.assertContains(adventure_contacts, "US-9908")
        self.assertContains(adventure_contacts, "Hunter Park 8")
        self.assertContains(adventure_contacts, "No Pin")
        self.assertEqual(self.journal.contacts.count(), 9)

        with patch("adventures.contact_log_views._unique_parks", return_value=parks):
            repeated = self.client.post(reverse("import_pota_hunter_log"), {
                "adventure": self.adventure.pk, "journal_entry": self.journal.pk,
                "pota_hunter_log": "\n".join(source_rows),
            })
        duplicate_preview = self.client.get(repeated.url)
        self.assertContains(duplicate_preview, "9 duplicates")
        self.assertEqual(JournalContact.objects.count(), 9)

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
