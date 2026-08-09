from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import resolve, reverse

from core.models import Adventure, JournalContact, JournalEntry, MemberProfile


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
        self.assertContains(detail, "View Contacts (0)")
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
        self.assertContains(detail, "View Contacts (2)")
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
        self.assertContains(detail, "View Contacts (1)")
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
