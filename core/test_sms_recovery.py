import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import authenticate, get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import MemberProfile
from .twilio_verify import (
    TwilioVerifyClient,
    TwilioVerifyConfiguration,
    TwilioVerifyError,
    configuration_diagnostics,
    load_twilio_configuration,
)


class TwilioConfigurationTests(TestCase):
    names = {
        "TWILIO_ACCOUNT_SID": "env-account",
        "TWILIO_API_KEY_SID": "env-key",
        "TWILIO_API_KEY_SECRET": "env-secret",
        "TWILIO_VERIFY_SERVICE_SID": "env-service",
    }

    def test_environment_configuration_loads(self):
        with patch.dict(os.environ, self.names, clear=True):
            config = load_twilio_configuration(base_dir="missing")
        self.assertTrue(config.complete)
        self.assertEqual(config.account_sid, "env-account")

    def test_environment_overrides_files_and_files_are_relative_to_base_dir(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            files = {
                "twilio_account_sid.txt": "file-account",
                "twilio_api_key_sid.txt": "file-key",
                "twilio_api_key_secret.txt": "file-secret",
                "twilio_verify_service_sid.txt": "file-service",
            }
            for name, value in files.items():
                (root / name).write_text(value, encoding="utf-8")
            with patch.dict(os.environ, {"TWILIO_ACCOUNT_SID": "env-account"}, clear=True):
                config = load_twilio_configuration(base_dir=root)
        self.assertEqual(config.account_sid, "env-account")
        self.assertEqual(config.api_key_sid, "file-key")
        self.assertEqual(config.api_key_secret, "file-secret")
        self.assertEqual(config.service_sid, "file-service")

    def test_missing_configuration_fails_safely_and_diagnostics_are_boolean(self):
        config = TwilioVerifyConfiguration("", "", "secret-value", "")
        with self.assertRaisesMessage(TwilioVerifyError, "configuration_missing"):
            TwilioVerifyClient(config).send_code("+16515551212")
        diagnostics = configuration_diagnostics(config)
        self.assertNotIn("secret-value", repr(diagnostics))
        self.assertTrue(diagnostics["Twilio API Key Secret configured"])

    def test_provider_logs_never_include_credentials(self):
        config = TwilioVerifyConfiguration("account-secret", "key-secret", "credential-secret", "service-secret")
        with patch("core.sms_views.messages.error"), self.assertLogs("core.sms_views", level=logging.WARNING) as captured:
            from .sms_views import _provider_error
            from django.test import RequestFactory
            request = RequestFactory().get("/")
            _provider_error(request, TwilioVerifyError("authentication_rejected"))
        output = " ".join(captured.output)
        for secret in (config.account_sid, config.api_key_sid, config.api_key_secret, config.service_sid):
            self.assertNotIn(secret, output)


@override_settings(SMS_RECOVERY_RATE_LIMIT=3, SMS_RECOVERY_VERIFY_LIMIT=3)
class SmsRecoveryWorkflowTests(TestCase):
    old_password = "OldRecoveryPass!942"
    new_password = "NewRecoveryPass!742"

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="rwagner", email="member@example.com", password=self.old_password
        )
        self.profile = MemberProfile.objects.create(
            user=self.user, callsign="W5RIK", mobile_phone="+16515551212"
        )

    def tearDown(self):
        cache.clear()

    def test_member_adds_phone_and_changed_number_becomes_unverified(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("mobile_phone_settings"), {"mobile_phone": "+16515550000"})
        self.assertRedirects(response, reverse("mobile_phone_settings"))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.mobile_phone, "+16515550000")
        self.assertIsNone(self.profile.phone_verified_at)

    @patch("core.sms_views.TwilioVerifyClient")
    def test_verification_send_and_correct_code_marks_phone_verified(self, client_class):
        self.client.force_login(self.user)
        sent = self.client.post(reverse("mobile_phone_send"))
        self.assertRedirects(sent, reverse("mobile_phone_verify"))
        client_class.return_value.send_code.assert_called_once_with("+16515551212")
        checked = self.client.post(reverse("mobile_phone_verify"), {"code": "123456"})
        self.assertRedirects(checked, reverse("mobile_phone_settings"))
        self.profile.refresh_from_db()
        self.assertIsNotNone(self.profile.phone_verified_at)

    @patch("core.sms_views.TwilioVerifyClient")
    def test_invalid_and_expired_codes_fail(self, client_class):
        self.client.force_login(self.user)
        self.client.post(reverse("mobile_phone_send"))
        for category in ("verification_failed", "verification_expired"):
            client_class.return_value.check_code.side_effect = TwilioVerifyError(category)
            response = self.client.post(reverse("mobile_phone_verify"), {"code": "123456"}, follow=True)
            self.assertContains(response, "invalid or has expired")
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.phone_verified_at)

    def test_sms_recovery_requires_verified_phone(self):
        response = self.client.post(reverse("sms_recovery_start"), {"identity": "W5RIK"}, follow=True)
        self.assertContains(response, "If the account is eligible")
        self.assertNotIn("sms_recovery_user_id", self.client.session)

    @patch("core.sms_views.TwilioVerifyClient")
    def test_successful_verification_allows_one_time_password_reset(self, client_class):
        self.profile.phone_verified_at = timezone.now()
        self.profile.save(update_fields=["phone_verified_at"])
        start = self.client.post(reverse("sms_recovery_start"), {"identity": "w5rik"})
        self.assertRedirects(start, reverse("sms_recovery_send"))
        send = self.client.post(reverse("sms_recovery_send"))
        self.assertRedirects(send, reverse("sms_recovery_verify"))
        verified = self.client.post(reverse("sms_recovery_verify"), {"code": "123456"})
        self.assertRedirects(verified, reverse("sms_recovery_reset"))
        reset = self.client.post(reverse("sms_recovery_reset"), {"new_password1": self.new_password, "new_password2": self.new_password})
        self.assertRedirects(reset, reverse("account_recovery_complete"))
        self.assertEqual(authenticate(username="rwagner", password=self.new_password), self.user)
        self.assertRedirects(self.client.get(reverse("sms_recovery_reset")), reverse("sms_recovery_start"))

    @patch("core.sms_views.TwilioVerifyClient")
    def test_password_validation_is_enforced(self, client_class):
        self.profile.phone_verified_at = timezone.now()
        self.profile.save(update_fields=["phone_verified_at"])
        session = self.client.session
        session["sms_recovery_approved_user_id"] = self.user.pk
        session.save()
        response = self.client.post(reverse("sms_recovery_reset"), {"new_password1": "short", "new_password2": "short"})
        self.assertContains(response, "too short")
        self.assertIsNotNone(authenticate(username="rwagner", password=self.old_password))

    def test_unauthorized_user_cannot_change_another_members_phone(self):
        other = get_user_model().objects.create_user(username="other", password=self.old_password)
        MemberProfile.objects.create(user=other, callsign="N0OTHER")
        self.client.force_login(other)
        self.client.post(reverse("mobile_phone_settings"), {"mobile_phone": "+16515559999"})
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.mobile_phone, "+16515551212")

    @override_settings(SMS_RECOVERY_RATE_LIMIT=1)
    def test_start_rate_limit_is_enforced(self):
        self.profile.phone_verified_at = timezone.now()
        self.profile.save(update_fields=["phone_verified_at"])
        self.client.post(reverse("sms_recovery_start"), {"identity": "W5RIK"}, REMOTE_ADDR="192.0.2.1")
        self.client.get(reverse("sms_recovery_start"))
        second = self.client.post(reverse("sms_recovery_start"), {"identity": "W5RIK"}, REMOTE_ADDR="192.0.2.1", follow=True)
        self.assertContains(second, "If the account is eligible")
