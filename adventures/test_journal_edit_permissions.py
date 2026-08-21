from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Adventure, JournalContact, JournalEntry, Location, MemberProfile


class JournalEditPermissionTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = self._verified_member(users, "journal-owner", "W0OWNER")
        self.other = self._verified_member(users, "journal-other", "W0OTHER")
        self.staff = users.objects.create_user(
            "journal-staff", password="test-password", is_staff=True
        )
        self.location = Location.objects.create(
            name="Journal Permission Park",
            created_by=self.owner,
            latitude="44.100000",
            longitude="-93.200000",
            visibility=Location.Visibility.PUBLIC,
        )
        self.adventure = Adventure.objects.create(
            owner=self.owner,
            title="Journal Permission Adventure",
            operating_callsign="W0OWNER",
            location=self.location,
            is_public=True,
        )
        self.journal = JournalEntry.objects.create(
            adventure=self.adventure,
            location=self.location,
            latitude=self.location.latitude,
            longitude=self.location.longitude,
            title="Original Journal Title",
            body="Original Journal body.",
            operating_callsign="W0OWNER",
            status=JournalEntry.Status.COMPLETED,
            is_public=True,
        )
        self.contact = JournalContact.objects.create(
            journal_entry=self.journal,
            callsign="K1TEST",
            qso_date=self.journal.entry_at.date(),
            fingerprint="journal-edit-permission-contact",
        )
        self.detail_url = reverse("journal_entry_detail", args=[self.journal.pk])
        self.edit_url = reverse("edit_journal_entry", args=[self.journal.pk])

    @staticmethod
    def _verified_member(users, username, callsign):
        user = users.objects.create_user(username, password="test-password")
        MemberProfile.objects.create(
            user=user,
            callsign=callsign,
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        return user

    def _edit_payload(self, *, title, body):
        return {
            "entry_at": self.journal.entry_at.strftime("%Y-%m-%dT%H:%M"),
            "status": JournalEntry.Status.COMPLETED,
            "is_public": "on",
            "location": str(self.location.pk),
            "location_name": self.location.name,
            "latitude": str(self.location.latitude),
            "longitude": str(self.location.longitude),
            "operating_callsign": "W0OWNER",
            "title": title,
            "body": body,
            "radio": "Portable radio",
            "antenna": "Wire antenna",
        }

    def test_owner_sees_edit_journal_button(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{self.edit_url}"')
        self.assertContains(response, "Edit Journal")

    def test_staff_sees_edit_journal_button(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{self.edit_url}"')
        self.assertContains(response, "Edit Journal")

    def test_other_member_does_not_see_edit_journal_button(self):
        self.client.force_login(self.other)
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, f'href="{self.edit_url}"')
        self.assertNotContains(response, "Edit Journal")

    def test_anonymous_visitor_does_not_see_edit_journal_button(self):
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, f'href="{self.edit_url}"')
        self.assertNotContains(response, "Edit Journal")

    def test_owner_can_open_and_submit_edit_form(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.edit_url).status_code, 200)
        response = self.client.post(
            self.edit_url,
            self._edit_payload(title="Owner Updated Journal", body="Updated by owner."),
        )
        self.assertRedirects(response, self.detail_url)
        self.journal.refresh_from_db()
        self.assertEqual(self.journal.title, "Owner Updated Journal")
        self.assertEqual(self.journal.adventure_id, self.adventure.pk)
        self.assertEqual(self.journal.location_id, self.location.pk)
        self.assertEqual(self.journal.status, JournalEntry.Status.COMPLETED)
        self.assertTrue(self.journal.contacts.filter(pk=self.contact.pk).exists())

    def test_staff_can_open_and_submit_edit_form(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.edit_url).status_code, 200)
        response = self.client.post(
            self.edit_url,
            self._edit_payload(title="Staff Updated Journal", body="Updated by staff."),
        )
        self.assertRedirects(response, self.detail_url)
        self.journal.refresh_from_db()
        self.assertEqual(self.journal.title, "Staff Updated Journal")
        self.assertEqual(self.journal.adventure_id, self.adventure.pk)
        self.assertEqual(self.journal.location_id, self.location.pk)
        self.assertEqual(self.journal.status, JournalEntry.Status.COMPLETED)
        self.assertTrue(self.journal.contacts.filter(pk=self.contact.pk).exists())

    def test_other_member_get_and_post_are_forbidden_and_cannot_modify_journal(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.edit_url).status_code, 403)
        response = self.client.post(
            self.edit_url,
            self._edit_payload(title="Forged Update", body="Unauthorized change."),
        )
        self.assertEqual(response.status_code, 403)
        self.journal.refresh_from_db()
        self.assertEqual(self.journal.title, "Original Journal Title")
        self.assertEqual(self.journal.body, "Original Journal body.")

    def test_anonymous_get_and_post_require_login_and_cannot_modify_journal(self):
        self.assertRedirects(
            self.client.get(self.edit_url),
            f"/accounts/login/?next={self.edit_url}",
        )
        response = self.client.post(
            self.edit_url,
            self._edit_payload(title="Anonymous Update", body="Unauthorized change."),
        )
        self.assertEqual(response.status_code, 302)
        self.journal.refresh_from_db()
        self.assertEqual(self.journal.title, "Original Journal Title")
        self.assertEqual(self.journal.body, "Original Journal body.")
