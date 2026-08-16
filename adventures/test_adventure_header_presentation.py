from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Adventure, JournalEntry, MemberProfile


class AdventureHeaderPresentationTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user("header-owner", password="test")
        MemberProfile.objects.create(
            user=self.owner,
            callsign="W0HEAD",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.other = users.objects.create_user("header-other", password="test")
        MemberProfile.objects.create(
            user=self.other,
            callsign="W0VIEW",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.adventure = Adventure.objects.create(
            owner=self.owner,
            title="Header Presentation Adventure",
            operating_callsign="W0HEAD",
            operating_callsign_url="https://example.com/event?id=346",
            is_public=True,
        )
        JournalEntry.objects.create(
            adventure=self.adventure,
            title="Open Journal",
            is_public=True,
            status=JournalEntry.Status.OPEN,
        )

    def test_header_keeps_calculated_status_without_visibility_controls(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.adventure.get_absolute_url())

        self.assertContains(
            response,
            'class="adventure-status adventure-status-active"',
        )
        self.assertContains(response, "Active")
        self.assertNotContains(response, "adventure-dashboard-state")
        self.assertNotContains(response, "Active / Public")
        self.assertNotContains(response, "Make Private")
        self.assertNotContains(
            response,
            reverse("toggle_adventure_visibility", args=[self.adventure.slug]),
        )

    def test_http_reference_is_a_safe_external_link_for_public_visitors(self):
        response = self.client.get(self.adventure.get_absolute_url())

        self.assertContains(response, "Event Website or Reference:")
        self.assertContains(
            response,
            '<a href="https://example.com/event?id=346" target="_blank" rel="noopener noreferrer">',
        )

    def test_https_reference_is_visible_to_signed_in_non_owner(self):
        self.client.force_login(self.other)
        response = self.client.get(self.adventure.get_absolute_url())

        self.assertContains(response, "Event Website or Reference:")
        self.assertContains(response, "https://example.com/event?id=346")
        self.assertNotContains(response, "Edit Adventure")

    def test_http_reference_is_linked(self):
        self.adventure.operating_callsign_url = "http://example.org/reference"
        self.adventure.save(update_fields=["operating_callsign_url"])

        response = self.client.get(self.adventure.get_absolute_url())

        self.assertContains(
            response,
            '<a href="http://example.org/reference" target="_blank" rel="noopener noreferrer">',
        )

    def test_plain_reference_is_escaped_and_not_linked(self):
        self.adventure.operating_callsign_url = "Field Day <script>alert(1)</script>"
        self.adventure.save(update_fields=["operating_callsign_url"])

        response = self.client.get(self.adventure.get_absolute_url())

        self.assertContains(response, "Event Website or Reference:")
        self.assertContains(
            response,
            "Field Day &lt;script&gt;alert(1)&lt;/script&gt;",
        )
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertNotContains(response, 'target="_blank"')

    def test_empty_reference_omits_the_complete_row(self):
        self.adventure.operating_callsign_url = "   "
        self.adventure.save(update_fields=["operating_callsign_url"])

        response = self.client.get(self.adventure.get_absolute_url())

        self.assertNotContains(response, "Event Website or Reference:")
        self.assertNotContains(response, "adventure-dashboard-reference")

    def test_footer_and_photos_heading_use_exact_required_copy(self):
        response = self.client.get(self.adventure.get_absolute_url())

        self.assertContains(
            response,
            "QSO’s and Contacts, Map Locations &amp; Photos are stored in Journals",
            html=True,
        )
        self.assertNotContains(response, "Status: QSO’s and Contacts")
        self.assertContains(response, "<h2>Photos</h2>", html=True)
        self.assertNotContains(response, "(Photos are stored in Journals)")

    def test_edit_form_retains_visibility_control_for_owner(self):
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("edit_adventure", args=[self.adventure.slug])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="is_public"')
        self.assertContains(response, "Visible to Everyone")

    def test_non_owner_cannot_open_edit_form(self):
        self.client.force_login(self.other)
        response = self.client.get(
            reverse("edit_adventure", args=[self.adventure.slug])
        )

        self.assertIn(response.status_code, (403, 404))
