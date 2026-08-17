import re

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import MemberProfile


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PASSWORD_RESET_DOMAIN="radiooutdoors.example",
    PASSWORD_RESET_USE_HTTPS=True,
    PASSWORD_RESET_RATE_LIMIT=20,
    PASSWORD_RESET_RATE_LIMIT_WINDOW=900,
)
class AccountRecoveryTests(TestCase):
    old_password = "OldRecoveryPass!942"
    new_password = "NewRecoveryPass!742"
    neutral_message = (
        "If an account matches that email, recovery instructions have been sent."
    )

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="W5RECOVER",
            email="member@example.com",
            password=self.old_password,
            first_name="Morgan",
        )
        MemberProfile.objects.create(
            user=self.user,
            callsign="W5RECOVER",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )

    def tearDown(self):
        cache.clear()

    def submit(self, email, follow=False):
        return self.client.post(
            reverse("account_recovery"),
            {"email": email},
            follow=follow,
            REMOTE_ADDR="192.0.2.10",
        )

    def reset_path_from_email(self):
        match = re.search(
            r"https://radiooutdoors\.example(/accounts/recovery/[^\s<]+)",
            mail.outbox[-1].body,
        )
        self.assertIsNotNone(match)
        return match.group(1)

    def test_login_page_links_to_recovery(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "Forgot password?")
        self.assertContains(response, reverse("account_recovery"))

    def test_login_page_links_to_member_registration(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "Create New Account")
        self.assertContains(
            response,
            f'href="{reverse("register")}"',
        )
        self.assertNotContains(response, "Follower account")

        self.client.force_login(self.user)
        signed_in = self.client.get(reverse("login"))
        self.assertNotContains(signed_in, "Create New Account")

    def test_known_and_unknown_submissions_show_identical_response(self):
        known = self.submit("member@example.com", follow=True)
        known_content = known.content
        self.assertContains(known, self.neutral_message)

        cache.clear()
        unknown = self.submit("missing@example.com", follow=True)
        self.assertContains(unknown, self.neutral_message)
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known_content, unknown.content)

    def test_known_active_user_receives_callsign_and_https_reset_link(self):
        response = self.submit("member@example.com")
        self.assertRedirects(response, reverse("account_recovery_done"))
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.from_email, "Radio Outdoors <info@radiooutdoors.org>")
        self.assertIn("W5RECOVER", message.body)
        self.assertIn("info@radiooutdoors.org", message.body)
        self.assertIn("https://radiooutdoors.example/accounts/recovery/", message.body)
        self.assertNotIn(self.old_password, message.body)

    def test_unknown_user_receives_no_email(self):
        self.submit("missing@example.com")
        self.assertEqual(mail.outbox, [])

    def test_valid_link_changes_password_and_is_one_time(self):
        self.submit("member@example.com")
        reset_path = self.reset_path_from_email()

        initial = self.client.get(reset_path)
        self.assertEqual(initial.status_code, 302)
        password_form_url = initial.url
        form = self.client.get(password_form_url)
        self.assertContains(form, "Choose a New Password")

        changed = self.client.post(
            password_form_url,
            {
                "new_password1": self.new_password,
                "new_password2": self.new_password,
            },
        )
        self.assertRedirects(changed, reverse("account_recovery_complete"))
        complete = self.client.get(reverse("account_recovery_complete"))
        self.assertContains(complete, "Return to Log In")

        self.assertIsNone(authenticate(username="W5RECOVER", password=self.old_password))
        self.assertEqual(
            authenticate(username="W5RECOVER", password=self.new_password),
            self.user,
        )
        reused = self.client.get(reset_path, follow=True)
        self.assertContains(reused, "invalid or has expired")

    def test_invalid_and_expired_links_are_rejected(self):
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        invalid = self.client.get(
            reverse(
                "account_recovery_confirm",
                kwargs={"uidb64": uid, "token": "invalid-token"},
            )
        )
        self.assertContains(invalid, "invalid or has expired")

        token = default_token_generator.make_token(self.user)
        with self.settings(PASSWORD_RESET_TIMEOUT=-1):
            expired = self.client.get(
                reverse(
                    "account_recovery_confirm",
                    kwargs={"uidb64": uid, "token": token},
                )
            )
        self.assertContains(expired, "invalid or has expired")

    @override_settings(PASSWORD_RESET_RATE_LIMIT=2)
    def test_rate_limit_suppresses_excess_recovery_email(self):
        responses = [
            self.submit("member@example.com", follow=True)
            for _ in range(3)
        ]
        self.assertEqual(len(mail.outbox), 2)
        for response in responses:
            self.assertContains(response, self.neutral_message)
