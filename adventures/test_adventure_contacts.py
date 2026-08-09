from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import resolve, reverse

from core.models import Adventure, JournalContact, JournalEntry, Location, MemberProfile, Photo

from .adif_parser import parse_adif_text
from .contact_map import MISSING_ORIGIN_MESSAGE, PRIVATE_ORIGIN_MESSAGE, build_contact_map


class AdventureContactHubTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            username="W5CONTACT", password="test-password"
        )
        MemberProfile.objects.create(
            user=self.owner, callsign="W5CONTACT", callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.other = user_model.objects.create_user(
            username="W5OTHER", password="test-password"
        )
        MemberProfile.objects.create(
            user=self.other, callsign="W5OTHER", callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.staff = user_model.objects.create_user(
            username="staff-contact", password="test-password", is_staff=True
        )
        self.adventure = Adventure.objects.create(
            owner=self.owner, title="Contact Hub Adventure", is_public=True
        )

    def add_entry(self, title, public=True):
        return JournalEntry.objects.create(
            adventure=self.adventure, title=title, body="Journal notes",
            is_public=public,
        )

    def add_contact(self, entry, callsign, fingerprint):
        return JournalContact.objects.create(
            journal_entry=entry, qso_date=date(2026, 8, 9),
            callsign=callsign, mode="SSB", fingerprint=fingerprint,
        )

    def test_adventure_controls_and_empty_hub_are_visible(self):
        self.client.force_login(self.owner)
        detail = self.client.get(self.adventure.get_absolute_url())
        self.assertContains(detail, "Import Contacts")
        self.assertNotContains(detail, "View Contacts (0)")
        self.assertContains(detail, "Import Contacts")
        hub = self.client.get(reverse("adventure_contacts", args=[self.adventure.slug]))
        self.assertContains(hub, "No contacts have been recorded for this Adventure.")

    def test_hub_aggregates_all_visible_journals_and_identifies_source(self):
        first = self.add_entry("Morning Journal")
        second = self.add_entry("Evening Journal")
        self.add_contact(first, "K1AAA", "first")
        self.add_contact(second, "K2BBB", "second")
        detail = self.client.get(self.adventure.get_absolute_url())
        hub = self.client.get(reverse("adventure_contacts", args=[self.adventure.slug]))
        self.assertContains(detail, "View Contacts")
        self.assertNotContains(detail, "View Contacts (2)")
        self.assertEqual(hub.context["contact_count"], 2)
        self.assertContains(hub, "K1AAA")
        self.assertContains(hub, "K2BBB")
        self.assertContains(hub, "Morning Journal")
        self.assertContains(hub, "Evening Journal")

    def test_public_hub_preserves_existing_journal_visibility(self):
        public_entry = self.add_entry("Public Journal", public=True)
        private_entry = self.add_entry("Private Journal", public=False)
        self.add_contact(public_entry, "K1PUBLIC", "public")
        self.add_contact(private_entry, "K1PRIVATE", "private")
        detail = self.client.get(self.adventure.get_absolute_url())
        hub = self.client.get(reverse("adventure_contacts", args=[self.adventure.slug]))
        self.assertContains(detail, "View Contacts")
        self.assertNotContains(detail, "View Contacts (1)")
        self.assertEqual(hub.context["contact_count"], 1)
        self.assertContains(hub, "K1PUBLIC")
        self.assertNotContains(hub, "K1PRIVATE")
        self.assertNotContains(hub, "Import Contacts")

    def test_no_journal_explains_requirement_and_links_create(self):
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("adventure_import_contacts", args=[self.adventure.slug])
        )
        self.assertContains(
            response,
            "Contacts are recorded through an Adventure Journal entry. Create a Journal entry before importing contacts.",
        )
        self.assertContains(response, "Create Journal Entry")
        self.assertContains(
            response,
            reverse("add_journal_entry", args=[self.adventure.slug]) + "?return_to=contacts",
        )

    def test_one_journal_displays_destination_before_continue(self):
        entry = self.add_entry("Only Journal")
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("adventure_import_contacts", args=[self.adventure.slug])
        )
        self.assertContains(response, "Contacts will be imported into this Journal entry:")
        self.assertContains(response, "Only Journal")
        self.assertContains(response, f'value="{entry.pk}"')

    def test_multiple_journals_require_explicit_destination(self):
        first = self.add_entry("First Destination")
        second = self.add_entry("Second Destination")
        self.client.force_login(self.owner)
        url = reverse("adventure_import_contacts", args=[self.adventure.slug])
        response = self.client.get(url)
        self.assertContains(response, "Choose the destination Journal entry")
        self.assertContains(response, 'name="journal_entry"', count=2)
        selected = self.client.post(url, {"journal_entry": second.pk})
        expected_return = reverse("adventure_contacts", args=[self.adventure.slug])
        self.assertRedirects(
            selected,
            reverse("import_adif", args=[second.pk]) + "?return_to=" + expected_return,
            fetch_redirect_response=False,
        )
        self.assertNotEqual(first.pk, second.pk)

    def test_destination_must_belong_to_same_adventure(self):
        self.add_entry("Owned Journal")
        other_adventure = Adventure.objects.create(
            owner=self.owner, title="Other Adventure", is_public=True
        )
        other_entry = JournalEntry.objects.create(
            adventure=other_adventure, title="Wrong Journal", body="Notes"
        )
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("adventure_import_contacts", args=[self.adventure.slug]),
            {"journal_entry": other_entry.pk},
        )
        self.assertEqual(response.status_code, 404)

    def test_unauthorized_member_cannot_import_and_staff_can(self):
        self.add_entry("Managed Journal")
        url = reverse("adventure_import_contacts", args=[self.adventure.slug])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_successful_existing_import_returns_to_hub_with_totals(self):
        entry = self.add_entry("Import Destination")
        self.client.force_login(self.owner)
        return_to = reverse("adventure_contacts", args=[self.adventure.slug])
        upload = SimpleUploadedFile(
            "contacts.adi",
            b"<CALL:5>K1ABC<QSO_DATE:8>20260809<MODE:3>SSB<EOR>",
            "text/plain",
        )
        preview = self.client.post(
            reverse("import_adif", args=[entry.pk]),
            {"adif_file": upload, "return_to": return_to},
        )
        self.assertEqual(preview.status_code, 302)
        token = resolve(preview.url).kwargs["token"]
        confirmation = self.client.post(
            reverse("confirm_adif_import", args=[entry.pk, token]),
            follow=True,
        )
        self.assertEqual(confirmation.resolver_match.url_name, "adventure_contacts")
        self.assertContains(confirmation, "1 imported; 0 skipped; 0 duplicates")
        self.assertContains(confirmation, "Destination Journal: Import Destination")
        self.assertContains(confirmation, "K1ABC")

        duplicate_upload = SimpleUploadedFile(
            "contacts.adi",
            b"<CALL:5>K1ABC<QSO_DATE:8>20260809<MODE:3>SSB<EOR>",
            "text/plain",
        )
        duplicate_preview = self.client.post(
            reverse("import_adif", args=[entry.pk]),
            {"adif_file": duplicate_upload, "return_to": return_to},
        )
        duplicate_token = resolve(duplicate_preview.url).kwargs["token"]
        duplicate_result = self.client.post(
            reverse("confirm_adif_import", args=[entry.pk, duplicate_token]),
            follow=True,
        )
        self.assertContains(duplicate_result, "0 imported; 1 skipped; 1 duplicate")
        self.assertEqual(entry.contacts.count(), 1)

    def test_invalid_import_stays_in_existing_workflow_with_error(self):
        entry = self.add_entry("Invalid Import Destination")
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("import_adif", args=[entry.pk]),
            {
                "adif_file": SimpleUploadedFile(
                    "invalid.adi", b"not an ADIF contact", "text/plain"
                ),
                "return_to": reverse("adventure_contacts", args=[self.adventure.slug]),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No valid contacts with callsign and QSO date were found.")
        self.assertEqual(entry.contacts.count(), 0)

    def test_contact_map_prefers_direct_coordinates_then_grid(self):
        location = Location.objects.create(
            name="Mapped Origin", created_by=self.owner,
            latitude="44.100000", longitude="-93.200000",
        )
        self.adventure.location = location
        self.adventure.save(update_fields=["location"])
        entry = self.add_entry("Map Journal")
        direct = self.add_contact(entry, "K1DIRECT", "direct-map")
        direct.latitude, direct.longitude, direct.grid_square = "40.100000", "-75.200000", "AA00AA"
        direct.save()
        grid = self.add_contact(entry, "K1GRID", "grid-map")
        grid.grid_square = "EN34"
        grid.save()
        unmapped = self.add_contact(entry, "K1NONE", "none-map")

        result = build_contact_map(self.adventure, [direct, grid, unmapped], self.owner)

        self.assertTrue(result["available"])
        self.assertEqual(result["mapped"], 2)
        self.assertEqual(result["unmapped"], 1)
        self.assertEqual(result["contacts"][0]["coordinate_source"], "Exact coordinates")
        self.assertEqual(result["contacts"][0]["latitude"], 40.1)
        self.assertEqual(result["contacts"][1]["coordinate_source"], "Grid-square center")
        self.assertTrue(result["contacts"][1]["approximate"])

    def test_missing_origin_uses_required_message_and_no_coordinates(self):
        entry = self.add_entry("No Origin")
        contact = self.add_contact(entry, "K1GRID", "no-origin")
        contact.grid_square = "EN34"
        contact.save()
        result = build_contact_map(self.adventure, [contact], self.owner)
        self.assertFalse(result["available"])
        self.assertEqual(result["message"], MISSING_ORIGIN_MESSAGE)
        self.assertIsNone(result["origin"])
        self.assertEqual(result["contacts"], [])

    def test_private_location_serializes_no_coordinates_for_visitor(self):
        location = Location.objects.create(
            name="Secret Cabin", created_by=self.owner,
            visibility=Location.Visibility.PRIVATE,
            latitude="47.123456", longitude="-93.654321",
        )
        self.adventure.location = location
        self.adventure.save(update_fields=["location"])
        entry = self.add_entry("Public Journal")
        contact = self.add_contact(entry, "K1SECRET", "private-origin")
        contact.latitude, contact.longitude = "41.123456", "-71.654321"
        contact.save()

        visitor = self.client.get(self.adventure.get_absolute_url())
        self.assertContains(visitor, PRIVATE_ORIGIN_MESSAGE)
        self.assertNotContains(visitor, "47.123456")
        self.assertNotContains(visitor, "-93.654321")
        self.assertNotContains(visitor, "41.123456")
        self.client.force_login(self.owner)
        owner = self.client.get(self.adventure.get_absolute_url())
        self.assertContains(owner, "47.123456")
        self.assertContains(owner, "41.123456")

    def test_contact_map_is_on_detail_and_hub_with_filters(self):
        location = Location.objects.create(
            name="Origin", created_by=self.owner,
            latitude="44.000000", longitude="-93.000000",
        )
        self.adventure.location = location
        self.adventure.save(update_fields=["location"])
        entry = self.add_entry("Mapped Journal")
        contact = self.add_contact(entry, "K1MAP", "map-page")
        contact.grid_square = "EN34"
        contact.band = "20m"
        contact.save()
        for url in [self.adventure.get_absolute_url(), reverse("adventure_contacts", args=[self.adventure.slug])]:
            response = self.client.get(url)
            self.assertContains(response, "Contacts From This Adventure")
            self.assertContains(response, 'data-contact-filter="journal"')
            self.assertContains(response, 'data-contact-filter="lines"')
            self.assertContains(response, "Grid-square center")

    def test_parser_preserves_radio_and_direct_coordinate_fields(self):
        parsed = parse_adif_text(
            "<CALL:5>K1ABC<QSO_DATE:8>20260809<BAND:3>20m<FREQ:6>14.250"
            "<LAT:10>N043 30.00<LON:10>W093 15.00<EOR>"
        )[0]
        self.assertEqual(parsed.band, "20M")
        self.assertEqual(parsed.frequency, 14.25)
        self.assertAlmostEqual(parsed.latitude, 43.5)
        self.assertAlmostEqual(parsed.longitude, -93.25)

    def test_summary_cards_link_to_existing_journal_and_contact_destinations(self):
        entry = self.add_entry("Summary Journal")
        self.add_contact(entry, "K1CARD", "summary-card-contact")

        response = self.client.get(self.adventure.get_absolute_url())

        self.assertContains(response, 'class="adventure-summary-card" href="#journal-entries"')
        self.assertContains(response, "View Journals")
        self.assertContains(
            response,
            f'class="adventure-summary-card" href="{reverse("adventure_contacts", args=[self.adventure.slug])}"',
        )
        self.assertContains(response, "View Contacts", count=1)
        self.assertNotContains(response, "View Contacts (1)")

    def test_zero_summary_actions_follow_owner_and_visitor_permissions(self):
        visitor = self.client.get(self.adventure.get_absolute_url())
        self.assertNotContains(visitor, "Add First Journal")
        self.assertNotContains(visitor, "Import Contacts")
        self.assertNotContains(visitor, "Add Photos")
        self.assertContains(visitor, "0</strong><span>Journals")
        self.assertContains(visitor, "0</strong><span>Contacts")
        self.assertContains(visitor, "0</strong><span>Photos")

        self.client.force_login(self.owner)
        owner = self.client.get(self.adventure.get_absolute_url())
        self.assertContains(owner, "Add First Journal")
        self.assertContains(owner, "Import Contacts", count=1)
        self.assertContains(owner, "Add Photos")
        self.assertContains(owner, reverse("add_journal_entry", args=[self.adventure.slug]))

    def test_photo_card_uses_gallery_and_hides_nonpublic_count_from_visitor(self):
        entry = self.add_entry("Photo Journal")
        Photo.objects.create(
            journal_entry=entry,
            image="adventure_photos/public-summary.jpg",
            moderation_status=Photo.ModerationStatus.APPROVED,
        )
        Photo.objects.create(
            journal_entry=entry,
            image="adventure_photos/pending-summary.jpg",
            moderation_status=Photo.ModerationStatus.PENDING,
        )

        visitor = self.client.get(self.adventure.get_absolute_url())
        self.assertContains(visitor, 'href="#adventure-photos"')
        self.assertContains(visitor, "1</strong><span>Photos")
        self.assertNotContains(visitor, "2</strong><span>Photos")

        self.client.force_login(self.owner)
        owner = self.client.get(self.adventure.get_absolute_url())
        self.assertContains(owner, "2</strong><span>Photos")
        self.assertContains(owner, "View Photos")

    def test_zero_photo_owner_uses_existing_journal_edit_upload_workflow(self):
        entry = self.add_entry("Photo Destination")
        self.client.force_login(self.owner)
        response = self.client.get(self.adventure.get_absolute_url())
        expected = reverse("edit_journal_entry", args=[entry.pk]) + "#journal-photo-upload"
        self.assertContains(response, f'href="{expected}"')
        self.assertContains(response, "Add Photos")
