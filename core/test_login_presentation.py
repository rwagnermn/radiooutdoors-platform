from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse


class LoginPresentationTests(TestCase):
    def test_login_uses_globe_layout_real_logo_and_accessible_html_controls(self):
        response = self.client.get(reverse("login"))

        self.assertContains(response, '<body class="login-page">')
        self.assertContains(response, '<h1 id="login-heading">Sign In</h1>')
        self.assertContains(response, "Welcome back to Radio Outdoors")
        self.assertContains(response, "images/radiooutdoors-logo-white.png")
        self.assertContains(response, "Username or Callsign")
        self.assertContains(response, 'name="password"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, "Forgot password?")
        self.assertContains(response, "Create New Account")

    def test_supplied_background_is_a_static_asset(self):
        background_path = finders.find("images/login-global-background.png")

        self.assertIsNotNone(background_path)
        self.assertGreater(Path(background_path).stat().st_size, 1_000_000)

    def test_invalid_credentials_keep_error_visible(self):
        response = self.client.post(
            reverse("login"),
            {"username": "missing-user", "password": "incorrect-password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Your username or password was not recognized.",
        )
        self.assertContains(response, 'role="alert"')

    def test_successful_login_preserves_authentication_redirect(self):
        user = get_user_model().objects.create_user(
            username="login-layout-user",
            password="valid-test-password",
        )

        response = self.client.post(
            reverse("login"),
            {
                "username": user.username,
                "password": "valid-test-password",
                "next": reverse("my_adventures"),
            },
        )

        self.assertRedirects(
            response,
            reverse("my_adventures"),
            fetch_redirect_response=False,
        )
