from datetime import datetime, timezone as datetime_timezone
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    FollowerInvitation, MemberProfile, PolicyAcceptance,
)
from .policies import (
    COMMUNITY_VERSION, PRIVACY_VERSION, TERMS_VERSION,
)
from .qrz_service import QRZNotFoundError, QRZResult


class PolicyRegistrationTests(TestCase):
    password = "CedarRidgeExpedition!942"

    def member_data(self, **overrides):
        data = {
            "callsign": "VE3POLICY",
            "email": "policy@example.com",
            "password1": self.password,
            "password2": self.password,
            "policy_accepted": "on",
            "age_confirmed": "on",
        }
        data.update(overrides)
        return data

    @patch("core.account_views.lookup_callsign")
    def test_neither_or_only_one_acceptance_creates_no_account(self, lookup):
        for payload in (
            self.member_data(policy_accepted="", age_confirmed=""),
            self.member_data(age_confirmed=""),
            self.member_data(policy_accepted=""),
        ):
            with self.subTest(payload=payload):
                response = self.client.post(reverse("register"), payload)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Required policy acceptance")
                self.assertFalse(get_user_model().objects.filter(email="policy@example.com").exists())
        lookup.assert_not_called()

    @patch("core.account_views.lookup_callsign")
    def test_verified_registration_records_exact_versions_and_utc_time(self, lookup):
        lookup.return_value = QRZResult(
            callsign="VE3POLICY", first_name="Pat", last_name="Operator",
            country="Canada", record_type="P",
        )
        before = timezone.now()
        response = self.client.post(reverse("register"), self.member_data())
        self.assertRedirects(response, reverse("member_welcome"))
        user = get_user_model().objects.get(username="VE3POLICY")
        acceptance = user.policy_acceptances.get()
        self.assertEqual(acceptance.terms_version, TERMS_VERSION)
        self.assertEqual(acceptance.privacy_version, PRIVACY_VERSION)
        self.assertEqual(acceptance.community_version, COMMUNITY_VERSION)
        self.assertEqual(acceptance.registration_path, "qrz_member")
        self.assertEqual(acceptance.account_status, "verified")
        self.assertTrue(acceptance.age_attested)
        self.assertGreaterEqual(acceptance.accepted_at, before)
        self.assertEqual(acceptance.accepted_at.utcoffset(), datetime_timezone.utc.utcoffset(None))

    @patch("core.account_views.lookup_callsign")
    def test_pending_registration_records_pending_path(self, lookup):
        lookup.side_effect = QRZNotFoundError("not found")
        response = self.client.post(
            reverse("register"),
            self.member_data(registration_action="manual"),
        )
        self.assertRedirects(response, reverse("manual_verification_request"))
        acceptance = PolicyAcceptance.objects.get()
        self.assertEqual(acceptance.registration_path, "pending_manual")
        self.assertEqual(acceptance.account_status, "pending")

    def test_invitation_registration_requires_and_records_acceptance(self):
        host = get_user_model().objects.create_user("W5HOSTPOLICY")
        profile = MemberProfile.objects.create(
            user=host, callsign="W5HOSTPOLICY", callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        invitation = FollowerInvitation.objects.create(
            member=profile, name="Invited Follower", email="follow-policy@example.com"
        )
        url = reverse("follower_register", kwargs={"token": invitation.token})
        rejected = self.client.post(url, {
            "email": invitation.email, "password1": self.password,
            "password2": self.password,
        })
        self.assertEqual(rejected.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(email=invitation.email).exists())
        accepted = self.client.post(url, {
            "email": invitation.email, "password1": self.password,
            "password2": self.password, "policy_accepted": "on",
            "age_confirmed": "on",
        })
        self.assertEqual(accepted.status_code, 302)
        record = PolicyAcceptance.objects.get(user__email=invitation.email)
        self.assertEqual(record.registration_path, "follower_invitation")

    def test_policy_links_open_separately_and_preserve_bound_values(self):
        response = self.client.post(
            reverse("register"),
            self.member_data(policy_accepted="", age_confirmed=""),
        )
        self.assertContains(response, 'value="VE3POLICY"')
        self.assertContains(response, 'value="policy@example.com"')
        for route in ("terms_of_use", "privacy_policy", "community_standards"):
            self.assertContains(response, reverse(route))
        self.assertContains(response, 'target="_blank"', count=3)
        self.assertContains(response, 'data-policy-required="true"', count=2)

    def test_member_registration_contains_complete_accessible_policy_dialog(self):
        response = self.client.get(reverse("register"))
        self.assertContains(response, "Read Required Policies")
        self.assertContains(response, "Required Radio Outdoors Policies")
        self.assertContains(response, 'role="dialog"')
        self.assertContains(response, 'aria-modal="true"')
        self.assertContains(response, 'aria-labelledby="required-policy-dialog-title"')
        self.assertContains(response, "Accept Required Policies")
        self.assertContains(response, "Close and Return to Registration", count=2)
        for text in (
            "Using Radio Outdoors", "Information collected", "Community conduct",
            TERMS_VERSION, PRIVACY_VERSION, COMMUNITY_VERSION,
        ):
            self.assertContains(response, text)
        self.assertNotContains(response, 'name="terms_version"')
        self.assertNotContains(response, 'name="privacy_version"')
        self.assertNotContains(response, 'name="community_version"')

    def test_follower_registration_uses_same_policy_dialog(self):
        host = get_user_model().objects.create_user("W5DIALOGHOST")
        profile = MemberProfile.objects.create(
            user=host, callsign="W5DIALOGHOST", callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        invitation = FollowerInvitation.objects.create(
            member=profile, name="Dialog Follower", email="dialog@example.com"
        )
        response = self.client.get(
            reverse("follower_register", kwargs={"token": invitation.token})
        )
        self.assertContains(response, "Read Required Policies")
        self.assertContains(response, "Required Radio Outdoors Policies")
        self.assertContains(response, "Accept Required Policies")

    def test_policy_dialog_script_does_not_store_or_transmit_form_values(self):
        script = (Path(settings.BASE_DIR) / "static" / "js" / "policy-review.js").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("localStorage", script)
        self.assertNotIn("sessionStorage", script)
        self.assertNotIn("fetch(", script)
        self.assertNotIn("XMLHttpRequest", script)
        self.assertIn("checkbox.checked = true", script)
        self.assertIn('event.key === "Escape"', script)
        self.assertIn('event.key !== "Tab"', script)
        self.assertIn("trigger.focus()", script)


class ExistingAccountPolicyTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "W5LEGACY", password="secret", email="legacy@example.com"
        )
        self.user.date_joined = datetime(2026, 8, 8, tzinfo=datetime_timezone.utc)
        self.user.save(update_fields=["date_joined"])
        MemberProfile.objects.create(
            user=self.user, callsign="W5LEGACY", callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.client.force_login(self.user)

    def acceptance_data(self, **extra):
        data = {"policy_accepted": "on", "age_confirmed": "on"}
        data.update(extra)
        return data

    def test_existing_member_is_gated_then_can_continue(self):
        destination = reverse("my_adventures")
        response = self.client.get(destination)
        self.assertRedirects(
            response,
            f"{reverse('policy_acceptance_required')}?next={destination}",
            fetch_redirect_response=False,
        )
        accepted = self.client.post(
            reverse("policy_acceptance_required"),
            self.acceptance_data(next=destination),
        )
        self.assertRedirects(accepted, destination)
        self.assertEqual(self.user.policy_acceptances.count(), 1)

    def test_missing_acceptance_remains_restricted_and_decline_preserves_account(self):
        response = self.client.post(reverse("policy_acceptance_required"), {})
        self.assertContains(response, "You must agree")
        declined = self.client.post(
            reverse("policy_acceptance_required"), {"action": "decline"}
        )
        self.assertRedirects(declined, reverse("policy_acceptance_declined"))
        self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())
        self.assertEqual(PolicyAcceptance.objects.count(), 0)

    def test_material_version_change_preserves_history_and_prompts_again(self):
        PolicyAcceptance.objects.create(
            user=self.user, account_identifier="W5LEGACY",
            terms_version="alpha-old", privacy_version="alpha-old",
            community_version="alpha-old", registration_path="existing_account",
            age_attested=True, account_status="verified",
        )
        response = self.client.get(reverse("account_home"))
        self.assertEqual(response.status_code, 302)
        gate = self.client.get(reverse("policy_acceptance_required"))
        self.assertContains(gate, "What changed")
        self.client.post(reverse("policy_acceptance_required"), self.acceptance_data())
        self.assertEqual(self.user.policy_acceptances.count(), 2)
        old = self.user.policy_acceptances.get(terms_version="alpha-old")
        with self.assertRaises(ValueError):
            old.save()


class PublicPolicyPageTests(TestCase):
    def test_policy_pages_are_public_versioned_and_linked_from_footer(self):
        for route in (
            "terms_of_use", "privacy_policy", "community_standards", "copyright_policy"
        ):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Alpha policy")
                self.assertContains(response, "Effective:")
        privacy = self.client.get(reverse("privacy_policy"))
        self.assertContains(privacy, "OpenAI")
        self.assertContains(privacy, "remain private")
        self.assertContains(privacy, "info@radiooutdoors.org")
        footer = self.client.get(reverse("home"))
        for text in ("Terms", "Privacy", "Community Standards", "Copyright/DMCA", "Contact"):
            self.assertContains(footer, text)
