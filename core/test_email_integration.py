import importlib.util
import os
from io import BytesIO
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import Adventure, JournalEntry, Location, MemberProfile, Photo
from .photo_moderation import moderate_photo
from .qrz_service import QRZConfigurationError


EMAIL_TEST_SETTINGS = {
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
    "RADIO_OUTDOORS_CONTACT_EMAIL": "info@radiooutdoors.org",
    "RADIO_OUTDOORS_ADMIN_EMAIL": "admin@radiooutdoors.org",
    "DEFAULT_FROM_EMAIL": "Radio Outdoors <info@radiooutdoors.org>",
    "SERVER_EMAIL": "Radio Outdoors System <admin@radiooutdoors.org>",
    "ADMINS": [("Radio Outdoors Administrator", "admin@radiooutdoors.org")],
    "RADIO_OUTDOORS_SITE_URL": "https://radiooutdoors.example",
}


def test_image():
    output = BytesIO()
    Image.new("RGB", (30, 20), "green").save(output, "PNG")
    return SimpleUploadedFile("email-test.png", output.getvalue(), "image/png")


@override_settings(**EMAIL_TEST_SETTINGS)
class OrganizationalEmailIntegrationTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_public_pages_expose_contact_but_not_admin_address(self):
        for route_name in ("help_center", "support_radio_outdoors"):
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name))
                self.assertContains(
                    response,
                    'href="mailto:info@radiooutdoors.org"',
                )
                self.assertNotContains(response, "admin@radiooutdoors.org")
                self.assertNotContains(response, "w5rik@radiooutdoors.org")
        help_page = self.client.get(reverse("help_center"))
        self.assertContains(help_page, "privacy questions or account-removal requests")

    @patch("core.account_views.lookup_callsign")
    def test_qrz_configuration_error_provides_support_link(self, lookup):
        lookup.side_effect = QRZConfigurationError("not configured")
        response = self.client.post(
            reverse("register"),
            {
                "callsign": "VE3EMAIL",
                "email": "applicant@example.net",
                "password1": "CedarRidgeExpedition!942",
                "password2": "CedarRidgeExpedition!942",
                "policy_accepted": "on",
                "age_confirmed": "on",
            },
        )
        self.assertContains(response, "Email Radio Outdoors Support")
        self.assertContains(response, 'mailto:info@radiooutdoors.org')
        self.assertNotContains(response, "admin@radiooutdoors.org")

    def test_follower_invitation_uses_public_sender_and_contact_footer(self):
        user = get_user_model().objects.create_user(
            "W5INVITE", email="member@example.net", password="password"
        )
        MemberProfile.objects.create(
            user=user,
            callsign="W5INVITE",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.client.force_login(user)
        response = self.client.post(
            reverse("invite_follower"),
            {"name": "Invited Follower", "email": "follower@example.net"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            mail.outbox[0].from_email,
            "Radio Outdoors <info@radiooutdoors.org>",
        )
        self.assertIn("info@radiooutdoors.org", mail.outbox[0].body)

    def test_new_manual_request_notifies_admin_once(self):
        user = get_user_model().objects.create_user(
            "VE3PENDING",
            email="pending@example.net",
            password="password",
        )
        MemberProfile.objects.create(
            user=user,
            callsign="VE3PENDING",
            callsign_verified=False,
        )
        self.client.force_login(user)
        data = {
            "full_name": "Bob Smith",
            "country": "Canada",
            "authority_url": "https://example.net/license/VE3PENDING",
            "explanation": "Authority listing attached by reference.",
        }
        with self.captureOnCommitCallbacks(execute=True):
            first = self.client.post(reverse("manual_verification_request"), data)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        notice = mail.outbox[0]
        self.assertEqual(notice.to, ["admin@radiooutdoors.org"])
        self.assertEqual(
            notice.from_email,
            "Radio Outdoors System <admin@radiooutdoors.org>",
        )
        self.assertIn("Applicant: Bob Smith", notice.body)
        self.assertIn("Callsign: VE3PENDING", notice.body)
        self.assertIn("https://radiooutdoors.example", notice.body)

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("manual_verification_request"), data)
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(
        MEDIA_ROOT=tempfile.mkdtemp(),
        PHOTO_MODERATION_BACKEND="core.test_photo_moderation.FailingProvider",
    )
    def test_moderation_failure_notifies_once_and_contains_no_photo(self):
        user = get_user_model().objects.create_user("W5PHOTO")
        location = Location.objects.create(name="Email Test Location")
        adventure = Adventure.objects.create(
            owner=user, title="Email Test Adventure", location=location
        )
        entry = JournalEntry.objects.create(adventure=adventure, body="Test")
        photo = Photo.objects.create(journal_entry=entry, image=test_image())
        second_photo = Photo.objects.create(
            journal_entry=entry,
            image=test_image(),
        )

        moderate_photo(photo)
        moderate_photo(photo)
        moderate_photo(second_photo)

        self.assertEqual(len(mail.outbox), 1)
        notice = mail.outbox[0]
        self.assertEqual(notice.to, ["admin@radiooutdoors.org"])
        self.assertIn(f"Photo record identifier: {photo.pk}", notice.body)
        self.assertIn("Failure category: ModerationUnavailable", notice.body)
        self.assertIn("https://radiooutdoors.example", notice.body)
        self.assertEqual(notice.attachments, [])

    def test_error_recipient_configuration_uses_private_address(self):
        self.assertEqual(settings.RADIO_OUTDOORS_CONTACT_EMAIL, "info@radiooutdoors.org")
        self.assertEqual(settings.RADIO_OUTDOORS_ADMIN_EMAIL, "admin@radiooutdoors.org")
        self.assertEqual(settings.ADMINS[0][1], "admin@radiooutdoors.org")
        self.assertIn("admin@radiooutdoors.org", settings.SERVER_EMAIL)


class OrganizationalEmailEnvironmentTests(TestCase):
    def test_environment_overrides_are_read_by_settings_module(self):
        settings_path = Path(settings.BASE_DIR) / "backend" / "settings.py"
        spec = importlib.util.spec_from_file_location(
            "radio_outdoors_email_override_test_settings",
            settings_path,
        )
        module = importlib.util.module_from_spec(spec)
        environment = {
            "RADIO_OUTDOORS_CONTACT_EMAIL": "contact-test@example.invalid",
            "RADIO_OUTDOORS_ADMIN_EMAIL": "admin-test@example.invalid",
        }
        with patch.dict(os.environ, environment, clear=False):
            spec.loader.exec_module(module)
        self.assertEqual(
            module.RADIO_OUTDOORS_CONTACT_EMAIL,
            "contact-test@example.invalid",
        )
        self.assertEqual(
            module.RADIO_OUTDOORS_ADMIN_EMAIL,
            "admin-test@example.invalid",
        )
        self.assertIn("contact-test@example.invalid", module.DEFAULT_FROM_EMAIL)
        self.assertIn("admin-test@example.invalid", module.SERVER_EMAIL)
        self.assertEqual(
            module.EMAIL_BACKEND,
            "django.core.mail.backends.console.EmailBackend",
        )

    def test_wikimedia_identifier_uses_public_contact_address(self):
        from .location_default_images import WIKIMEDIA_USER_AGENT

        self.assertIn("info@radiooutdoors.org", WIKIMEDIA_USER_AGENT)
        self.assertNotIn("contact@radiooutdoors.org", WIKIMEDIA_USER_AGENT)
