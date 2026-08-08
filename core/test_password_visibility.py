from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.test import TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


class PasswordVisibilityControlTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="W5EYE",
            email="eye@example.com",
            password="EyeControlPass!942",
        )

    def assert_shared_control_loaded(self, response):
        self.assertContains(response, "js/password-visibility.js")

    def test_login_and_registration_load_shared_control(self):
        for route in ["login", "register"]:
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assert_shared_control_loaded(response)
                self.assertContains(response, 'type="password"')

    def test_reset_confirmation_loads_shared_control(self):
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        response = self.client.get(
            reverse(
                "account_recovery_confirm",
                kwargs={"uidb64": uid, "token": token},
            ),
            follow=True,
        )
        self.assert_shared_control_loaded(response)
        self.assertContains(response, 'type="password"', count=2)

    def test_password_change_loads_shared_control(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("password_change"))
        self.assert_shared_control_loaded(response)
        self.assertContains(response, 'type="password"', count=3)
