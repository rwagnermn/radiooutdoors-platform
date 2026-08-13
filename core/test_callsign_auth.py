from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import MemberProfile


class UsernameOrCallsignLoginTests(TestCase):
    password = "CedarRidgeExpedition!942"

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="rwagner",
            password=self.password,
        )
        MemberProfile.objects.create(
            user=self.user,
            callsign="W5RIK",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )

    def login(self, login_name, password=None):
        return self.client.post(
            reverse("login"),
            {"username": login_name, "password": password or self.password},
        )

    def test_login_by_existing_username_succeeds(self):
        response = self.login("rwagner")
        self.assertRedirects(response, reverse("my_adventures"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_login_by_exact_callsign_succeeds(self):
        response = self.login("W5RIK")
        self.assertRedirects(response, reverse("my_adventures"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_login_by_mixed_case_callsign_succeeds(self):
        response = self.login("w5rIk")
        self.assertRedirects(response, reverse("my_adventures"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_wrong_password_with_valid_callsign_fails(self):
        response = self.login("W5RIK", "incorrect-password")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_unknown_callsign_fails(self):
        response = self.login("N0UNKNOWN")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_member_cannot_login_by_callsign(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        response = self.login("W5RIK")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_staff_username_login_remains_unchanged(self):
        staff = get_user_model().objects.create_user(
            username="siteadmin",
            password=self.password,
            is_staff=True,
        )
        response = self.login("siteadmin")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), staff.pk)

    def test_exact_username_takes_precedence_over_another_members_callsign(self):
        callsign_owner = get_user_model().objects.create_user(
            username="another-login",
            password="DifferentPassword!731",
        )
        MemberProfile.objects.create(user=callsign_owner, callsign="rwagner")

        response = self.login("rwagner")
        self.assertRedirects(response, reverse("my_adventures"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_login_page_labels_shared_field_for_username_or_callsign(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "Username or Callsign")


class ManageMembersLoginNameTests(TestCase):
    def test_manage_members_displays_login_name_and_callsign_separately(self):
        staff = get_user_model().objects.create_user(
            username="siteadmin",
            password="CedarRidgeExpedition!942",
            is_staff=True,
        )
        member = get_user_model().objects.create_user(username="rwagner")
        MemberProfile.objects.create(user=member, callsign="W5RIK")
        self.client.force_login(staff)

        response = self.client.get(reverse("member_admin_list"))

        self.assertContains(response, "<th>Login Name</th>", html=True)
        self.assertContains(response, "<th>Callsign</th>", html=True)
        self.assertContains(response, "<td>rwagner</td>", html=True)
        self.assertContains(response, "<strong>W5RIK</strong>", html=True)
