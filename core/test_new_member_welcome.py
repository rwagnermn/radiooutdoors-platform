from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import MemberProfile
from .qrz_service import QRZResult


class NewMemberWelcomeTests(TestCase):
    password = "CedarRidgeExpedition!942"

    def registration_data(self, callsign="VE3WELCOME", email="welcome@example.com"):
        return {
            "callsign": callsign,
            "email": email,
            "password1": self.password,
            "password2": self.password,
            "policy_accepted": "on",
            "age_confirmed": "on",
        }

    def qrz_result(self, first_name="Casey"):
        return QRZResult(
            callsign="VE3WELCOME",
            first_name=first_name,
            last_name="Operator" if first_name else "",
            city="Toronto",
            state="ON",
            country="Canada",
            grid="FN03",
            license_class="",
            expires="",
        )

    @patch("core.account_views.lookup_callsign")
    def test_successful_registration_redirects_to_named_welcome_with_actions(self, lookup):
        lookup.return_value = self.qrz_result()
        response = self.client.post(reverse("register"), self.registration_data())
        self.assertRedirects(response, reverse("member_welcome"))

        welcome = self.client.get(reverse("member_welcome"))
        self.assertContains(welcome, "Welcome to Radio Outdoors, Casey!")
        self.assertContains(
            welcome,
            "Your callsign has been verified, and your Member account is ready. What would you like to do first?",
        )
        self.assertContains(welcome, reverse("add_adventure"))
        self.assertContains(welcome, reverse("locations"))
        self.assertContains(welcome, reverse("create_location"))
        self.assertContains(welcome, reverse("my_adventures"))
        self.assertContains(welcome, reverse("home"))
        self.assertNotContains(welcome, reverse("all_adventures"))

    def test_welcome_falls_back_to_callsign_when_first_name_is_unavailable(self):
        user = get_user_model().objects.create_user("VE3WELCOME", password=self.password)
        MemberProfile.objects.create(
            user=user,
            callsign="VE3WELCOME",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.client.force_login(user)
        response = self.client.get(reverse("member_welcome"))
        self.assertContains(response, "Welcome to Radio Outdoors, VE3WELCOME!")

    def test_pending_follower_and_visitor_cannot_use_verified_welcome(self):
        pending = get_user_model().objects.create_user("VE3PENDING")
        MemberProfile.objects.create(user=pending, callsign="VE3PENDING")
        follower = get_user_model().objects.create_user("follower@example.com")

        self.assertEqual(self.client.get(reverse("member_welcome")).status_code, 302)
        for user in (pending, follower):
            self.client.force_login(user)
            self.assertRedirects(
                self.client.get(reverse("member_welcome")), reverse("account_home")
            )

    def test_ordinary_login_still_redirects_to_my_adventures(self):
        user = get_user_model().objects.create_user(
            "VE3RETURN", password=self.password
        )
        MemberProfile.objects.create(
            user=user,
            callsign="VE3RETURN",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        response = self.client.post(
            reverse("login"), {"username": "VE3RETURN", "password": self.password}
        )
        self.assertRedirects(response, reverse("my_adventures"))
