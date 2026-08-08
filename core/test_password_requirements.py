from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.test import TestCase
from django.urls import reverse
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes

from .models import FollowerInvitation, MemberProfile


class PasswordRequirementStatusTests(TestCase):
    def post_status(self, password, **identity):
        return self.client.post(
            reverse("password_requirement_status"),
            {"password": password, **identity},
        )

    def test_statuses_are_reported_by_djangos_configured_validators(self):
        response = self.post_status(
            "CedarRidgeExpedition!942",
            username="W5RULE",
            email="member@example.com",
            first_name="Rick",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["requirements"],
            {
                "minimum_length": True,
                "not_similar": True,
                "not_common": True,
                "not_numeric": True,
            },
        )

        common = self.post_status("password").json()["requirements"]
        self.assertTrue(common["minimum_length"])
        self.assertFalse(common["not_common"])
        self.assertTrue(common["not_numeric"])

        numeric = self.post_status("12345678").json()["requirements"]
        self.assertFalse(numeric["not_numeric"])

        similar = self.post_status("W5RULE", username="W5RULE").json()[
            "requirements"
        ]
        self.assertFalse(similar["not_similar"])

    def test_empty_password_starts_with_every_requirement_needed(self):
        response = self.post_status("")
        self.assertTrue(
            all(value is False for value in response.json()["requirements"].values())
        )

    def test_endpoint_is_post_only_and_not_cached(self):
        self.assertEqual(
            self.client.get(reverse("password_requirement_status")).status_code,
            405,
        )
        response = self.post_status("CedarRidgeExpedition!942")
        self.assertIn("no-cache", response.headers["Cache-Control"])

    def test_authenticated_check_uses_current_account_identity(self):
        user = get_user_model().objects.create_user(
            username="W5RULE", email="member@example.com", password="OldPass!942"
        )
        self.client.force_login(user)
        statuses = self.post_status("W5RULE").json()["requirements"]
        self.assertFalse(statuses["not_similar"])


class PasswordRequirementTemplateTests(TestCase):
    requirement_text = (
        "Be at least 8 characters long",
        "Not be too similar to your callsign, name, or email address",
        "Not be a commonly used password",
        "Not be entirely numbers",
    )

    def assert_requirements(self, response):
        self.assertContains(response, "Your password must:")
        for text in self.requirement_text:
            self.assertContains(response, text)
        self.assertContains(response, 'data-password-requirements')
        self.assertContains(response, "password-requirements.js")

    def test_member_registration_shows_requirements_before_password(self):
        response = self.client.get(reverse("register"))
        self.assert_requirements(response)
        html = response.content.decode()
        self.assertLess(html.index("data-password-requirements"), html.index('id="id_password1"'))

    def test_follower_registration_shows_requirements_before_password(self):
        host_user = get_user_model().objects.create_user("W5HOST")
        host = MemberProfile.objects.create(
            user=host_user, callsign="W5HOST", callsign_verified=True
        )
        invitation = FollowerInvitation.objects.create(
            member=host, name="Invited Person", email="follower@example.com"
        )
        response = self.client.get(
            reverse("follower_register", kwargs={"token": invitation.token})
        )
        self.assert_requirements(response)
        html = response.content.decode()
        self.assertLess(html.index("data-password-requirements"), html.index('id="id_password1"'))

    def test_password_reset_shows_requirements_before_new_password(self):
        user = get_user_model().objects.create_user(
            "W5RESET", email="reset@example.com", password="OldPass!942"
        )
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        response = self.client.get(
            reverse("password_reset_confirm", kwargs={"uidb64": uid, "token": token}),
            follow=True,
        )
        self.assert_requirements(response)
        html = response.content.decode()
        self.assertLess(
            html.index("data-password-requirements"), html.index('id="id_new_password1"')
        )

    def test_logged_in_password_change_shows_requirements_in_correct_position(self):
        user = get_user_model().objects.create_user(
            "W5CHANGE", email="change@example.com", password="OldPass!942"
        )
        self.client.force_login(user)
        response = self.client.get(reverse("password_change"))
        self.assert_requirements(response)
        html = response.content.decode()
        checklist = html.index("data-password-requirements")
        self.assertGreater(checklist, html.index('id="id_old_password"'))
        self.assertLess(checklist, html.index('id="id_new_password1"'))
