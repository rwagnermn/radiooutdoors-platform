from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import JournalContact, MemberProfile


class ContactBulkDeleteTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("W5BULK", password="password")
        MemberProfile.objects.create(user=self.owner, callsign="W5BULK", callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ)
        self.other = get_user_model().objects.create_user("N0OTHER", password="password")
        MemberProfile.objects.create(user=self.other, callsign="N0OTHER", callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ)
        self.contacts = [JournalContact.objects.create(owner=self.owner, qso_date="2026-08-11",
            callsign=f"K1{i}", fingerprint=f"owned-{i}",
            source=JournalContact.Source.POTA_HUNTER if i < 2 else JournalContact.Source.MANUAL)
            for i in range(3)]
        self.foreign = JournalContact.objects.create(owner=self.other, qso_date="2026-08-11",
            callsign="K9FOREIGN", fingerprint="foreign-contact")
        self.client.force_login(self.owner)

    def test_log_renders_page_selection_and_row_checkboxes(self):
        response = self.client.get(reverse("my_contact_log"))
        self.assertContains(response, "Select all contacts on this page")
        self.assertContains(response, 'class="contact-log-row-checkbox"', count=3)
        self.assertContains(response, "0 selected")

    def test_confirmation_and_delete_are_scoped_to_owned_selected_contacts(self):
        url = reverse("bulk_delete_contacts")
        selected = [self.contacts[0].pk, self.contacts[1].pk, self.foreign.pk]
        confirmation = self.client.post(url, {"contact_ids": selected})
        self.assertContains(confirmation, "Delete 2 selected Contacts?")
        self.assertContains(confirmation, "Delete Selected Contacts")
        response = self.client.post(url, {"contact_ids": selected, "confirm_delete": "1"})
        self.assertRedirects(response, reverse("my_contact_log"))
        self.assertFalse(JournalContact.objects.filter(pk__in=[c.pk for c in self.contacts[:2]]).exists())
        self.assertTrue(JournalContact.objects.filter(pk=self.contacts[2].pk).exists())
        self.assertTrue(JournalContact.objects.filter(pk=self.foreign.pk).exists())

    def test_filtered_page_contains_only_filtered_selectable_rows(self):
        response = self.client.get(reverse("my_contact_log"), {"source": JournalContact.Source.POTA_HUNTER})
        self.assertContains(response, 'class="contact-log-row-checkbox"', count=2)
        self.assertNotContains(response, f'value="{self.contacts[2].pk}" class="contact-log-row-checkbox"')
