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

    def test_dashboard_deduplicates_same_contact_across_visible_journals(self):
        first = self.add_entry("Morning Journal")
        second = self.add_entry("Backup Journal")
        self.add_contact(first, "K1SAME", "same-qso")
        self.add_contact(second, "K1SAME", "same-qso")

        detail = self.client.get(self.adventure.get_absolute_url())

        self.assertEqual(detail.context["contact_count"], 1)
        self.assertContains(detail, "K1SAME", count=1)

    def test_dashboard_omits_contacts_from_private_journals_for_visitors(self):
        public_entry = self.add_entry("Public Journal", public=True)
        private_entry = self.add_entry("Private Journal", public=False)
        self.add_contact(public_entry, "K1VISIBLE", "visible-qso")
        self.add_contact(private_entry, "K1HIDDEN", "hidden-qso")

        detail = self.client.get(self.adventure.get_absolute_url())

        self.assertContains(detail, "K1VISIBLE")
        self.assertNotContains(detail, "K1HIDDEN")

    def test_dashboard_qso_columns_use_contact_geography_without_journal_column(self):
        entry = self.add_entry("Geography Journal")
        contact = self.add_contact(entry, "K1GEO", "geo-qso")
        contact.band = "20m"
        contact.state = "Minnesota"
        contact.country = "USA"
        contact.save(update_fields=["band", "state", "country"])

        detail = self.client.get(self.adventure.get_absolute_url())

        self.assertContains(detail, "<th>State</th>", html=True)
        self.assertContains(detail, "<th>Country</th>", html=True)
        self.assertNotContains(detail, "<th>Journal</th>", html=True)
        self.assertContains(detail, "Minnesota")
        self.assertContains(detail, "USA")

    def test_dashboard_journal_cards_render_details_and_viewer_counts(self):
        location = Location.objects.create(name="Eleven Lake", created_by=self.owner)
        entry = JournalEntry.objects.create(
            adventure=self.adventure,
            location=location,
            title="Morning at Eleven Lake",
            body="Notes",
            status=JournalEntry.Status.COMPLETED,
            is_public=True,
        )
        self.add_contact(entry, "K1COUNT", "count-qso")
        Photo.objects.create(
            journal_entry=entry,
            image="adventure_photos/approved-count.jpg",
            moderation_status=Photo.ModerationStatus.APPROVED,
        )
        Photo.objects.create(
            journal_entry=entry,
            image="adventure_photos/pending-count.jpg",
            moderation_status=Photo.ModerationStatus.PENDING,
        )

        visitor = self.client.get(self.adventure.get_absolute_url())

        self.assertContains(visitor, "Morning at Eleven Lake")
        self.assertContains(visitor, "Eleven Lake")
        self.assertContains(visitor, "Complete")
        entry_row = next(item for item in visitor.context["journal_entries"] if item.pk == entry.pk)
        self.assertEqual(entry_row.dashboard_contact_count, 1)
        self.assertEqual(entry_row.dashboard_photo_count, 1)

        self.client.force_login(self.owner)
        owner = self.client.get(self.adventure.get_absolute_url())
        owner_row = next(item for item in owner.context["journal_entries"] if item.pk == entry.pk)
        self.assertEqual(owner_row.dashboard_photo_count, 2)

    def test_dashboard_summary_and_map_include_accessible_compact_controls(self):
        self.adventure.summary = "A long field report. " * 40
        self.adventure.save(update_fields=["summary"])
        location = Location.objects.create(
            name="Mapped Camp", created_by=self.owner,
            latitude="44.100000", longitude="-93.200000",
        )
        JournalEntry.objects.create(
            adventure=self.adventure, location=location,
            latitude=location.latitude, longitude=location.longitude,
            title="Mapped Journal", body="Notes",
        )
        source = self.client.get(self.adventure.get_absolute_url()).content.decode()

        self.assertIn("data-summary-clamp", source)
        self.assertIn('data-summary-toggle aria-expanded="false" hidden', source)
        self.assertIn("View Full Map", source)

    def test_dashboard_uses_centered_pencil_side_panel_wrapper(self):
        from django.conf import settings

        css = (settings.BASE_DIR / "static" / "css" / "style.css").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'background-image: url("../images/adventure-detail-pencil-background.png")',
            css,
        )
        self.assertIn(
            "body.adventure-dashboard-page .content.adventure-dashboard", css
        )
        self.assertIn("width: min(1240px, calc(100% - 560px))", css)
        self.assertIn("max-width: 1240px", css)

    def test_unapproved_dashboard_photo_is_blurred_for_owner_and_clear_for_staff(self):
        entry = self.add_entry("Moderation Journal")
        Photo.objects.create(
            journal_entry=entry,
            image="adventure_photos/pending-dashboard.jpg",
            moderation_status=Photo.ModerationStatus.PENDING,
        )

        self.client.force_login(self.owner)
        owner = self.client.get(self.adventure.get_absolute_url())
        self.assertContains(owner, "adventure-photo-unapproved")
        self.assertContains(owner, "Photo awaiting approval")

        self.client.force_login(self.staff)
        staff = self.client.get(self.adventure.get_absolute_url())
        self.assertNotContains(staff, "adventure-photo-unapproved")
        self.assertContains(staff, "journal-photo-viewer-trigger")

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

    def test_successful_existing_import_returns_to_journal_with_totals(self):
        entry = self.add_entry("Import Destination")
        self.client.force_login(self.owner)
        return_to = reverse("adventure_contacts", args=[self.adventure.slug])
        upload = SimpleUploadedFile(
            "contacts.adi",
            (
                b"<CALL:5>K1ABC<QSO_DATE:8>20260809<MODE:3>SSB<EOR>"
                b"<CALL:5>K2BAD<EOR>"
            ),
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
        self.assertEqual(confirmation.resolver_match.url_name, "journal_entry_detail")
        self.assertContains(confirmation, "1 contacts imported successfully.")
        self.assertNotContains(confirmation, "duplicate contact")
        self.assertContains(confirmation, "1 invalid contact skipped.")
        self.assertContains(confirmation, "Contacts — 1")
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
        self.assertEqual(duplicate_result.resolver_match.url_name, "journal_entry_detail")
        self.assertContains(duplicate_result, "0 contacts imported successfully.")
        self.assertContains(duplicate_result, "1 duplicate contact skipped.")
        self.assertNotContains(duplicate_result, "invalid contact")
        self.assertContains(duplicate_result, "Contacts — 1")
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
        self.assertEqual(response.resolver_match.url_name, "import_adif")
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

    def test_contact_map_uses_visible_resolved_park_as_approximate_pin(self):
        origin = Location.objects.create(
            name="Mapped Origin", created_by=self.owner,
            latitude="44.100000", longitude="-93.200000",
        )
        park = Location.objects.create(
            name="Nearby Park", created_by=self.owner,
            visibility=Location.Visibility.PRIVATE,
            latitude="36.454000", longitude="-94.034000",
        )
        self.adventure.location = origin
        self.adventure.save(update_fields=["location"])
        contact = self.add_contact(self.add_entry("Hunter Map"), "K1PARK", "resolved-map")
        contact.resolved_location = park
        contact.save(update_fields=["resolved_location"])

        owner_result = build_contact_map(self.adventure, [contact], self.owner)
        self.assertEqual(owner_result["mapped"], 1)
        self.assertEqual(owner_result["contacts"][0]["coordinate_source"], "Approximate resolved park location")
        self.assertTrue(owner_result["contacts"][0]["approximate"])
        self.assertEqual(owner_result["contacts"][0]["latitude"], 36.454)

        visitor_result = build_contact_map(self.adventure, [contact], self.other)
        self.assertEqual(visitor_result["mapped"], 0)
        self.assertEqual(visitor_result["unmapped"], 1)

    def test_journal_map_contains_only_its_contacts_and_primary_location(self):
        origin = Location.objects.create(
            name="Journal Origin", created_by=self.owner,
            latitude="44.100000", longitude="-93.200000",
        )
        destination_a = Location.objects.create(
            name="Journal A Park", created_by=self.owner,
            latitude="36.454000", longitude="-94.034000",
        )
        destination_b = Location.objects.create(
            name="Journal B Park", created_by=self.owner,
            latitude="40.000000", longitude="-90.000000",
        )
        self.adventure.location = origin
        self.adventure.save(update_fields=["location"])
        journal_a = self.add_entry("Journal A")
        journal_b = self.add_entry("Journal B")
        contact_a = self.add_contact(journal_a, "K1JOURNALA", "journal-a-map")
        contact_a.resolved_location = destination_a
        contact_a.save(update_fields=["resolved_location"])
        contact_b = self.add_contact(journal_b, "K1JOURNALB", "journal-b-map")
        contact_b.resolved_location = destination_b
        contact_b.save(update_fields=["resolved_location"])
        no_pin = self.add_contact(journal_a, "K1NOPIN", "journal-no-pin")

        self.client.force_login(self.owner)
        response = self.client.get(reverse("journal_entry_detail", args=[journal_a.pk]))
        self.assertContains(response, "Contacts From This Journal")
        self.assertContains(response, "Journal Origin")
        self.assertContains(response, "K1JOURNALA")
        self.assertNotContains(response, "K1JOURNALB")
        self.assertContains(response, "1 mapped of 2 total contacts")
        self.assertContains(response, "K1NOPIN")

    def test_contact_only_hunter_location_is_absent_from_global_map(self):
        normal = Location.objects.create(
            name="Normal Global Location", created_by=self.owner,
            latitude="44.100000", longitude="-93.200000",
        )
        contact_only = Location.objects.create(
            name="Hunter Contact Destination", created_by=self.owner,
            visibility=Location.Visibility.PRIVATE,
            latitude="36.454000", longitude="-94.034000",
            description="Created from POTA Hunter Log import. Coordinate source: geocoded park name.",
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse("map_explorer"))
        self.assertContains(response, normal.name)
        self.assertNotContains(response, contact_only.name)

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
        self.assertNotContains(owner, "41.123456")
        self.assertContains(owner, "K1SECRET")

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
        dashboard = self.client.get(self.adventure.get_absolute_url())
        self.assertContains(dashboard, "QSO’s and Contacts")
        self.assertContains(dashboard, "K1MAP")
        self.assertNotContains(dashboard, 'data-contact-filter="lines"')

        hub = self.client.get(reverse("adventure_contacts", args=[self.adventure.slug]))
        self.assertContains(hub, "Contacts From This Adventure")
        self.assertContains(hub, 'data-contact-filter="journal"')
        self.assertContains(hub, 'data-contact-filter="lines"')
        self.assertContains(hub, "Grid-square center")

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

        self.assertNotContains(response, "adventure-story-stats")
        self.assertContains(response, 'id="journal-entries"')
        self.assertContains(response, f'href="{reverse("adventure_contacts", args=[self.adventure.slug])}"')
        self.assertContains(response, "View Contacts", count=1)
        self.assertNotContains(response, "View Contacts (1)")

    def test_zero_summary_actions_follow_owner_and_visitor_permissions(self):
        visitor = self.client.get(self.adventure.get_absolute_url())
        self.assertNotContains(visitor, "Add First Journal")
        self.assertNotContains(visitor, "Import Contacts")
        self.assertNotContains(visitor, "Add Photos")
        self.assertContains(visitor, "No journal entries yet.")
        self.assertContains(visitor, "No contacts have been recorded")
        self.assertContains(visitor, "No photos have been added yet.")

        self.client.force_login(self.owner)
        owner = self.client.get(self.adventure.get_absolute_url())
        self.assertNotContains(owner, "Add First Journal")
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
        self.assertContains(visitor, 'id="adventure-photos"')
        self.assertContains(visitor, "1 photo")
        self.assertNotContains(visitor, "2 photos")

        self.client.force_login(self.owner)
        owner = self.client.get(self.adventure.get_absolute_url())
        self.assertContains(owner, "2 photos")
        self.assertContains(owner, "adventure-photo-strip")

    def test_zero_photo_owner_uses_existing_journal_edit_upload_workflow(self):
        entry = self.add_entry("Photo Destination")
        self.client.force_login(self.owner)
        response = self.client.get(self.adventure.get_absolute_url())
        expected = reverse("edit_journal_entry", args=[entry.pk]) + "#journal-photo-upload"
        self.assertContains(response, f'href="{expected}"')
        self.assertContains(response, "Add Photos")

    def test_adventure_dashboard_preserves_document_scroll_and_scopes_overflow(self):
        from django.conf import settings

        css = (settings.BASE_DIR / "static" / "css" / "style.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("html{min-height:100%;scroll-behavior:smooth;}", css)
        self.assertIn("overflow-x:hidden;overflow-y:auto;", css)
        self.assertIn(".adventure-dashboard-page main {\n    min-height:", css)
        self.assertNotIn(".adventure-dashboard-page main {\n    height: 100vh", css)
        self.assertIn(
            ".adventure-dashboard-grid > section { min-width: 0; min-height: 264px; height: auto; padding: 12px 14px; overflow: visible; }",
            css,
        )
        self.assertIn(
            ".adventure-dashboard-scroll { max-height: 214px; overflow: auto;",
            css,
        )
        self.assertIn(".adventure-photo-strip", css)
        self.assertIn("overflow-x: auto; overflow-y: hidden;", css)

        viewer_js = (
            settings.BASE_DIR / "static" / "js" / "journal-photo-viewer.js"
        ).read_text(encoding="utf-8")
        self.assertIn('dialog.addEventListener("close"', viewer_js)
        self.assertNotIn("document.body.style.overflow", viewer_js)
        self.assertNotIn('classList.add("modal-open")', viewer_js)
