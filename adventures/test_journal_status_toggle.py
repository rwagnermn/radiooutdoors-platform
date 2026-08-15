from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from core.models import Adventure, JournalEntry, MemberProfile


class JournalStatusToggleTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user("status-owner", password="test-password")
        MemberProfile.objects.create(
            user=self.owner,
            callsign="W0OWN",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.other = user_model.objects.create_user("status-other", password="test-password")
        MemberProfile.objects.create(
            user=self.other,
            callsign="W0OTH",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.staff = user_model.objects.create_user("status-staff", password="test-password", is_staff=True)
        self.adventure = Adventure.objects.create(owner=self.owner, title="Status Adventure")
        self.entry = JournalEntry.objects.create(
            adventure=self.adventure,
            title="Status Journal",
            body="Status-only test body.",
            operating_callsign="W0OWN",
        )
        self.url = reverse("toggle_journal_status", args=[self.entry.pk])

    def test_internal_values_display_as_active_and_complete(self):
        self.assertEqual(self.entry.status, "open")
        self.assertEqual(self.entry.display_status_label, "Active")
        self.entry.status = JournalEntry.Status.COMPLETED
        self.assertEqual(self.entry.display_status_label, "Complete")

    def test_owner_toggles_both_directions_and_only_status_changes(self):
        self.client.force_login(self.owner)
        before = {
            "title": self.entry.title,
            "body": self.entry.body,
            "is_public": self.entry.is_public,
            "location_id": self.entry.location_id,
            "operating_callsign": self.entry.operating_callsign,
        }
        response = self.client.post(self.url, {"next": reverse("journal_entry_detail", args=[self.entry.pk])})
        self.assertRedirects(response, reverse("journal_entry_detail", args=[self.entry.pk]))
        self.entry.refresh_from_db()
        self.adventure.refresh_from_db()
        self.assertEqual(self.entry.status, JournalEntry.Status.COMPLETED)
        self.assertEqual(self.adventure.status, Adventure.Status.COMPLETED)
        self.assertEqual(before, {key: getattr(self.entry, key) for key in before})

        self.client.post(self.url)
        self.entry.refresh_from_db()
        self.adventure.refresh_from_db()
        self.assertEqual(self.entry.status, JournalEntry.Status.OPEN)
        self.assertEqual(self.adventure.status, Adventure.Status.ACTIVE)

    def test_staff_can_toggle_but_other_member_cannot(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(self.url).status_code, 403)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, JournalEntry.Status.OPEN)

        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(self.url).status_code, 302)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, JournalEntry.Status.COMPLETED)

    def test_visitor_get_forged_id_and_csrf_do_not_change_status(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(
            self.client.post(reverse("toggle_journal_status", args=[self.entry.pk + 9999])).status_code,
            404,
        )
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(csrf_client.post(self.url).status_code, 403)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, JournalEntry.Status.OPEN)

    def test_owner_sees_button_and_unauthorized_viewers_see_badge(self):
        detail_url = reverse("journal_entry_detail", args=[self.entry.pk])
        self.client.force_login(self.owner)
        owner_response = self.client.get(detail_url)
        self.assertContains(owner_response, 'aria-label="Change Journal status to Complete"')
        self.assertContains(owner_response, ">Active</button>")
        self.assertNotContains(owner_response, ">Open</")

        self.client.force_login(self.other)
        other_response = self.client.get(detail_url)
        self.assertContains(other_response, ">Active</span>")
        self.assertNotContains(other_response, self.url)

        self.client.logout()
        visitor_response = self.client.get(detail_url)
        self.assertContains(visitor_response, ">Active</span>")
        self.assertNotContains(visitor_response, self.url)

    def test_last_active_rollup_and_multiple_journal_rollup(self):
        second = JournalEntry.objects.create(
            adventure=self.adventure,
            body="Second Journal.",
            operating_callsign="W0OWN",
            status=JournalEntry.Status.COMPLETED,
        )
        self.adventure.refresh_from_db()
        self.assertEqual(self.adventure.status, Adventure.Status.ACTIVE)
        self.client.force_login(self.owner)
        self.client.post(self.url)
        self.adventure.refresh_from_db()
        self.assertEqual(self.adventure.status, Adventure.Status.COMPLETED)
        self.client.post(reverse("toggle_journal_status", args=[second.pk]))
        self.adventure.refresh_from_db()
        self.assertEqual(self.adventure.status, Adventure.Status.ACTIVE)
