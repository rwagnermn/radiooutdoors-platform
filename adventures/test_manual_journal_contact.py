from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Adventure, JournalContact, JournalEntry, MemberProfile


class ManualJournalContactTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="W5OWNER", password="password")
        MemberProfile.objects.create(user=self.owner, callsign="W5OWNER", callsign_verified=True, verification_method=MemberProfile.VerificationMethod.QRZ)
        self.adventure = Adventure.objects.create(owner=self.owner, title="Portable Day", operating_callsign="W5OWNER", is_public=True)
        self.journal = JournalEntry.objects.create(adventure=self.adventure, title="Morning Session", body="Notes", operating_callsign="W5OWNER", is_public=True)
        self.url = reverse("add_journal_contact", args=[self.journal.pk])

    def test_owner_sees_add_contact_and_saves_unified_contact(self):
        self.client.force_login(self.owner)
        detail = self.client.get(reverse("journal_entry_detail", args=[self.journal.pk]))
        self.assertContains(detail, "Add Contact")
        response = self.client.post(self.url, {
            "qso_date": "2026-08-11", "time_on": "15:04", "callsign": "k1abc",
            "band": "20M", "mode": "SSB", "frequency": "14.250000",
            "signal_report": "59", "comment": "Strong signal",
            "pota_park_reference": "us-1234", "pota_park_name": "Pike Lake",
        })
        self.assertRedirects(response, reverse("journal_entry_detail", args=[self.journal.pk]))
        contact = JournalContact.objects.get()
        self.assertEqual(contact.owner, self.owner)
        self.assertEqual(contact.adventure, self.adventure)
        self.assertEqual(contact.journal_entry, self.journal)
        self.assertEqual(contact.source, JournalContact.Source.MANUAL)
        self.assertEqual(contact.callsign, "K1ABC")
        self.assertEqual(contact.signal_report, "59")
        self.assertEqual(contact.pota_park_reference, "US-1234")

        journal_detail = self.client.get(reverse("journal_entry_detail", args=[self.journal.pk]))
        self.assertContains(journal_detail, "K1ABC")
        self.assertContains(journal_detail, "Contacts")
        adventure_contacts = self.client.get(reverse("adventure_contacts", args=[self.adventure.slug]))
        self.assertContains(adventure_contacts, "K1ABC")
        my_adventures = self.client.get(reverse("my_adventures"))
        self.assertContains(my_adventures, '<td class="adventure-col-count adventure-col-contacts center-column">1</td>')

    def test_empty_journal_always_shows_contact_section_and_actions(self):
        self.client.force_login(self.owner)
        detail = self.client.get(reverse("journal_entry_detail", args=[self.journal.pk]))
        self.assertContains(detail, "Contacts — 0")
        self.assertContains(detail, "No Contacts have been added to this Journal yet.")
        self.assertContains(detail, "Add Contact")
        self.assertContains(detail, "Import POTA Hunter Log")

    def test_unauthorized_member_cannot_add_contact(self):
        other = get_user_model().objects.create_user(username="N0OTHER", password="password")
        MemberProfile.objects.create(user=other, callsign="N0OTHER", callsign_verified=True, verification_method=MemberProfile.VerificationMethod.QRZ)
        self.client.force_login(other)
        self.assertNotContains(self.client.get(reverse("journal_entry_detail", args=[self.journal.pk])), "Add Contact")
        self.assertNotContains(
            self.client.get(reverse("journal_entry_detail", args=[self.journal.pk])),
            reverse("import_pota_hunter_log") + f"?journal_entry={self.journal.pk}",
        )
        self.assertEqual(self.client.get(self.url).status_code, 403)
        import_url = reverse("import_pota_hunter_log") + f"?journal_entry={self.journal.pk}"
        self.assertEqual(self.client.get(import_url).status_code, 404)
        self.assertEqual(JournalContact.objects.count(), 0)

    def test_staff_can_use_manual_contact_form(self):
        staff = get_user_model().objects.create_user(username="STAFF", password="password", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url).status_code, 200)
