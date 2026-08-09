from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .auth import is_verified_member
from .models import ManualVerificationRequest, MemberProfile
from .qrz_service import QRZNotFoundError, QRZUnavailableError


class ManualVerificationRegistrationTests(TestCase):
    registration_data = {
        "callsign": "VE3PENDING",
        "email": "pending@example.com",
        "password1": "CedarRidgeExpedition!942",
        "password2": "CedarRidgeExpedition!942",
        "policy_accepted": "on",
        "age_confirmed": "on",
    }

    @patch("core.account_views.lookup_callsign")
    def test_confirmed_not_found_offers_manual_verification_only(self, lookup):
        lookup.side_effect = QRZNotFoundError("not found")
        response = self.client.post(reverse("register"), self.registration_data)
        self.assertContains(response, "QRZ could not verify this callsign.")
        self.assertContains(
            response, "Licensed amateur-radio operator but not listed in QRZ?"
        )
        self.assertContains(response, "Request Manual Verification")
        self.assertContains(
            response,
            "Callsign not found: QRZ successfully responded, but this callsign was not found.",
        )
        self.assertFalse(
            get_user_model().objects.filter(username="VE3PENDING").exists()
        )

    @patch("core.account_views.lookup_callsign")
    def test_manual_selection_creates_restricted_pending_account(self, lookup):
        lookup.side_effect = QRZNotFoundError("not found")
        response = self.client.post(
            reverse("register"),
            {**self.registration_data, "registration_action": "manual"},
        )
        self.assertRedirects(response, reverse("manual_verification_request"))
        user = get_user_model().objects.get(username="VE3PENDING")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        self.assertFalse(user.member_profile.callsign_verified)
        self.assertEqual(
            user.member_profile.verification_method,
            MemberProfile.VerificationMethod.NONE,
        )
        self.assertFalse(user.member_profile.profile_is_public)
        self.assertFalse(is_verified_member(user))

    @patch("core.account_views.lookup_callsign")
    def test_transport_failure_never_offers_manual_verification(self, lookup):
        lookup.side_effect = QRZUnavailableError("timeout")
        response = self.client.post(reverse("register"), self.registration_data)
        self.assertContains(response, "QRZ is temporarily unavailable")
        self.assertNotContains(response, "Request Manual Verification")
        self.assertFalse(
            get_user_model().objects.filter(username="VE3PENDING").exists()
        )


class ManualVerificationWorkflowTests(TestCase):
    def setUp(self):
        self.pending_user = get_user_model().objects.create_user(
            "VE3PENDING",
            email="pending@example.com",
            password="CedarRidgeExpedition!942",
        )
        self.profile = MemberProfile.objects.create(
            user=self.pending_user,
            callsign="VE3PENDING",
            profile_is_public=False,
            callsign_verified=False,
        )
        self.pending_client = Client()
        self.pending_client.force_login(self.pending_user)

        self.verified_user = get_user_model().objects.create_user("W5VERIFIED")
        MemberProfile.objects.create(
            user=self.verified_user,
            callsign="W5VERIFIED",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.follower = get_user_model().objects.create_user("follower@example.com")
        self.staff = get_user_model().objects.create_user(
            "staff", is_staff=True, is_superuser=True
        )

    def request_data(self):
        return {
            "full_name": "Bob Smith",
            "country": "Canada",
            "authority_url": "https://ised-isde.canada.ca/radio-authorizations/",
            "explanation": "My license appears in the Canadian authority database.",
        }

    def create_request(self):
        return ManualVerificationRequest.objects.create(
            member=self.profile,
            full_name="Bob Smith",
            country="Canada",
            authority_url="https://ised-isde.canada.ca/radio-authorizations/",
        )

    def test_pending_header_identity_and_pending_menu(self):
        response = self.pending_client.get(reverse("home"))
        self.assertContains(response, "Pending — VE3PENDING")
        self.assertContains(response, "Verification Status")
        self.assertContains(response, "Complete/Edit Verification Request")
        self.assertContains(response, "Change Password")
        self.assertNotContains(response, "My Adventures")

        response = self.pending_client.post(
            reverse("manual_verification_request"), self.request_data()
        )
        self.assertRedirects(response, reverse("manual_verification_status"))
        response = self.pending_client.get(reverse("home"))
        self.assertContains(response, "Pending — Bob Smith")

    def test_pending_has_visitor_equivalent_browsing_and_publishing_limits(self):
        self.assertEqual(self.pending_client.get(reverse("all_adventures")).status_code, 200)
        self.assertEqual(self.pending_client.get(reverse("locations")).status_code, 200)
        self.assertEqual(self.pending_client.get(reverse("add_adventure")).status_code, 403)
        self.assertEqual(self.pending_client.get(reverse("create_location")).status_code, 403)

    def test_only_pending_members_can_open_and_submit_request_form(self):
        url = reverse("manual_verification_request")
        self.assertEqual(self.client.get(url).status_code, 302)
        for user in (self.follower, self.verified_user):
            client = Client()
            client.force_login(user)
            self.assertEqual(client.get(url).status_code, 403)
            self.assertEqual(client.post(url, self.request_data()).status_code, 403)
        self.assertEqual(self.pending_client.get(url).status_code, 200)
        self.assertEqual(self.pending_client.post(url, self.request_data()).status_code, 302)

    def test_status_page_shows_reviewer_message_and_allows_resubmission(self):
        verification_request = self.create_request()
        verification_request.status = ManualVerificationRequest.Status.REJECTED
        verification_request.reviewer_message = "Please provide a direct authority record link."
        verification_request.save()
        response = self.pending_client.get(reverse("manual_verification_status"))
        self.assertContains(response, "Not Approved")
        self.assertContains(response, "Please provide a direct authority record link.")

        self.pending_client.post(reverse("manual_verification_request"), self.request_data())
        verification_request.refresh_from_db()
        self.assertEqual(verification_request.status, ManualVerificationRequest.Status.PENDING)
        self.assertEqual(verification_request.reviewer_message, "")

    def test_staff_queue_permissions_and_approval_transition_are_immediate(self):
        verification_request = self.create_request()
        queue_url = reverse("manual_verification_queue")
        self.assertEqual(self.client.get(queue_url).status_code, 302)
        ordinary = Client()
        ordinary.force_login(self.verified_user)
        self.assertEqual(ordinary.get(queue_url).status_code, 302)

        staff_client = Client()
        staff_client.force_login(self.staff)
        response = staff_client.post(
            reverse(
                "manual_verification_review",
                kwargs={"request_id": verification_request.pk},
            ),
            {"action": "approve", "reviewer_message": "License confirmed."},
        )
        self.assertRedirects(response, queue_url)
        self.profile.refresh_from_db()
        verification_request.refresh_from_db()
        self.assertTrue(self.profile.callsign_verified)
        self.assertEqual(
            self.profile.verification_method,
            MemberProfile.VerificationMethod.MANUAL,
        )
        self.assertEqual(self.profile.verified_by, self.staff)
        self.assertIsNotNone(self.profile.verification_at)
        self.assertEqual(
            verification_request.status,
            ManualVerificationRequest.Status.APPROVED,
        )

        response = self.pending_client.get(reverse("home"))
        self.assertContains(response, "VE3PENDING - Bob")
        self.assertNotContains(response, "Pending —")
        self.assertContains(response, "My Adventures")
        self.assertNotEqual(
            self.pending_client.get(reverse("add_adventure")).status_code, 403
        )
