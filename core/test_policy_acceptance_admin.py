from datetime import datetime, timezone as datetime_timezone
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import formats, timezone

from .models import MemberProfile, PolicyAcceptance


class PolicyAcceptanceAdminTests(TestCase):
    def setUp(self):
        self.viewer = get_user_model().objects.create_user(
            "auditviewer", password="secret", is_staff=True
        )
        self.viewer.user_permissions.add(
            Permission.objects.get(codename="view_policyacceptance")
        )
        self.member = get_user_model().objects.create_user(
            "W5AUDIT", password="secret", email="operator@example.com",
            first_name="Ada", last_name="Operator",
        )
        MemberProfile.objects.create(
            user=self.member, callsign="W5AUDIT", callsign_verified=True
        )
        self.acceptance = PolicyAcceptance.objects.create(
            user=self.member,
            account_identifier="W5AUDIT",
            terms_version="alpha-2026-08-09",
            privacy_version="alpha-2026-08-09",
            community_version="alpha-2026-08-09",
            age_attested=True,
            registration_path="qrz_member",
            account_status="verified",
        )
        self.list_url = reverse("admin:core_policyacceptance_changelist")
        self.detail_url = reverse(
            "admin:core_policyacceptance_change", args=[self.acceptance.pk]
        )
        self.client.force_login(self.viewer)

    def test_authorized_staff_can_list_search_filter_and_view(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        for text in (
            "W5AUDIT", "verified", "alpha-2026-08-09", "qrz_member",
        ):
            self.assertContains(response, text)

        searched = self.client.get(self.list_url, {"q": "Ada Operator"})
        self.assertContains(searched, "W5AUDIT")
        filtered = self.client.get(self.list_url, {
            "account_status__exact": "verified",
            "terms_version__exact": "alpha-2026-08-09",
        })
        self.assertContains(filtered, "W5AUDIT")

        detail = self.client.get(self.detail_url)
        self.assertEqual(detail.status_code, 200)
        self.assertContains(
            detail,
            "Policy acceptance records are permanent audit history and cannot be edited.",
        )
        self.assertContains(detail, "Ada Operator")
        self.assertContains(detail, "Age attestation")

    def test_local_display_time_preserves_utc_storage(self):
        stored = datetime(2026, 8, 9, 3, 30, tzinfo=datetime_timezone.utc)
        PolicyAcceptance.objects.filter(pk=self.acceptance.pk).update(accepted_at=stored)
        self.acceptance.refresh_from_db()
        self.assertEqual(self.acceptance.accepted_at, stored)
        timezone.activate(ZoneInfo("America/Chicago"))
        try:
            expected = formats.date_format(
                timezone.localtime(stored), "DATETIME_FORMAT"
            )
            self.assertContains(self.client.get(self.detail_url), expected)
        finally:
            timezone.deactivate()

    def test_add_change_delete_and_direct_post_are_denied(self):
        original = {
            "terms_version": self.acceptance.terms_version,
            "account_status": self.acceptance.account_status,
            "user_id": self.acceptance.user_id,
        }
        add_url = reverse("admin:core_policyacceptance_add")
        delete_url = reverse(
            "admin:core_policyacceptance_delete", args=[self.acceptance.pk]
        )
        self.assertEqual(self.client.get(add_url).status_code, 403)
        self.assertEqual(self.client.post(add_url, {}).status_code, 403)
        self.assertEqual(
            self.client.post(self.detail_url, {
                "terms_version": "tampered",
                "account_status": "pending",
            }).status_code,
            403,
        )
        self.assertEqual(self.client.get(delete_url).status_code, 403)
        self.assertEqual(self.client.post(delete_url, {"post": "yes"}).status_code, 403)
        self.acceptance.refresh_from_db()
        self.assertEqual(
            {
                "terms_version": self.acceptance.terms_version,
                "account_status": self.acceptance.account_status,
                "user_id": self.acceptance.user_id,
            },
            original,
        )

    def test_unauthorized_accounts_cannot_access_history(self):
        accounts = []
        ordinary = get_user_model().objects.create_user("W5ORDINARY", password="secret")
        MemberProfile.objects.create(
            user=ordinary, callsign="W5ORDINARY", callsign_verified=True
        )
        accounts.append(ordinary)
        pending = get_user_model().objects.create_user("W5PENDING", password="secret")
        MemberProfile.objects.create(
            user=pending, callsign="W5PENDING", callsign_verified=False
        )
        accounts.append(pending)
        accounts.append(get_user_model().objects.create_user("follower", password="secret"))

        for account in accounts:
            with self.subTest(account=account.username):
                self.client.force_login(account)
                self.assertNotEqual(self.client.get(self.list_url).status_code, 200)
        self.client.logout()
        self.assertNotEqual(self.client.get(self.list_url).status_code, 200)

    def test_multiple_versions_and_deactivated_user_remain_readable(self):
        PolicyAcceptance.objects.create(
            user=self.member,
            account_identifier="W5AUDIT",
            terms_version="alpha-older",
            privacy_version="alpha-older",
            community_version="alpha-older",
            age_attested=True,
            registration_path="existing_account_reacceptance",
            account_status="verified",
        )
        self.member.is_active = False
        self.member.save(update_fields=["is_active"])
        response = self.client.get(self.list_url, {"q": "W5AUDIT"})
        self.assertContains(response, "2 policy acceptances")
        self.assertContains(response, "alpha-older")
        self.assertContains(response, "alpha-2026-08-09")

    def test_staff_menu_link_requires_view_permission(self):
        home = self.client.get(reverse("home"))
        self.assertContains(home, "Policy Acceptance History")
        unprivileged_staff = get_user_model().objects.create_user(
            "staffwithoutview", password="secret", is_staff=True
        )
        self.client.force_login(unprivileged_staff)
        home = self.client.get(reverse("home"))
        self.assertNotContains(home, "Policy Acceptance History")
        self.assertNotEqual(self.client.get(self.list_url).status_code, 200)
