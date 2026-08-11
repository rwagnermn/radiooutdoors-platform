from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .account_forms import MemberRegistrationForm
from .models import (
    Adventure,
    JournalContact,
    JournalEntry,
    MemberProfile,
    Photo,
    PotaActivationImport,
    PotaImportBatch,
)


class AccountDeactivationTests(TestCase):
    password = "StrongPass!942"

    def setUp(self):
        user_model = get_user_model()
        self.member = user_model.objects.create_user(
            username="W5PAUSE",
            password=self.password,
            email="pause@example.com",
        )
        self.profile = MemberProfile.objects.create(
            user=self.member,
            callsign="W5PAUSE",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.ADMIN,
        )
        self.admin = user_model.objects.create_superuser(
            username="reactivation-admin",
            password=self.password,
            email="admin@example.com",
        )

    def _create_operational_history(self):
        adventure = Adventure.objects.create(
            owner=self.member,
            title="Preserved Adventure",
            is_public=True,
        )
        journal = JournalEntry.objects.create(
            adventure=adventure,
            title="Preserved Journal",
            body="History remains.",
        )
        contact = JournalContact.objects.create(
            journal_entry=journal,
            qso_date=date(2026, 8, 11),
            callsign="W1KEEP",
            fingerprint="preserved-contact",
        )
        photo = Photo.objects.create(
            journal_entry=journal,
            image="adventure_photos/preserved.jpg",
        )
        batch = PotaImportBatch.objects.create(owner=self.member)
        activation = PotaActivationImport.objects.create(
            adventure=adventure,
            batch=batch,
            activation_date=date(2026, 8, 11),
            callsign="W5PAUSE",
            park_reference="US-0002",
            park_name="Preserved Park",
            fingerprint="preserved-activation",
            location_resolution="unresolved",
        )
        return adventure, journal, contact, photo, batch, activation

    def _self_deactivate(self):
        self.client.force_login(self.member)
        return self.client.post(
            reverse("deactivate_account"),
            {"callsign": "W5PAUSE"},
        )

    def test_member_can_confirm_self_deactivation_and_is_logged_out(self):
        self.client.force_login(self.member)
        confirmation = self.client.get(reverse("deactivate_account"))
        self.assertContains(confirmation, "Deactivation is reversible")
        self.assertContains(confirmation, "POTA imports and history")

        response = self.client.post(
            reverse("deactivate_account"),
            {"callsign": "W5PAUSE"},
        )

        self.member.refresh_from_db()
        self.assertFalse(self.member.is_active)
        self.assertContains(response, "Account Deactivated")
        self.assertContains(response, "signed out")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_deactivation_preserves_all_operational_history(self):
        records = self._create_operational_history()

        self._self_deactivate()

        for record in records:
            with self.subTest(model=type(record).__name__):
                self.assertTrue(type(record).objects.filter(pk=record.pk).exists())
        self.assertTrue(get_user_model().objects.filter(pk=self.member.pk).exists())
        self.assertTrue(MemberProfile.objects.filter(pk=self.profile.pk).exists())

    def test_inactive_member_cannot_log_in_and_is_hidden_publicly(self):
        self._self_deactivate()

        self.assertFalse(
            self.client.login(username="W5PAUSE", password=self.password)
        )
        member_list = self.client.get(reverse("members"))
        self.assertNotContains(member_list, "W5PAUSE")
        detail = self.client.get(
            reverse("member_detail", kwargs={"callsign": "W5PAUSE"})
        )
        self.assertEqual(detail.status_code, 404)

    def test_public_adventure_and_historical_attribution_remain(self):
        adventure, *_ = self._create_operational_history()
        self._self_deactivate()

        detail = self.client.get(adventure.get_absolute_url())

        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "W5PAUSE")
        self.assertNotContains(detail, reverse("my_member_profile"))

    def test_admin_can_reactivate_and_member_can_log_in_again(self):
        self._self_deactivate()
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("member_reactivate", args=[self.profile.pk]),
            follow=True,
        )

        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)
        self.assertContains(response, "W5PAUSE was reactivated")
        self.client.logout()
        self.assertTrue(
            self.client.login(username="W5PAUSE", password=self.password)
        )

    def test_admin_can_explicitly_deactivate_member(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("member_deactivate", args=[self.profile.pk]),
            follow=True,
        )

        self.member.refresh_from_db()
        self.assertFalse(self.member.is_active)
        self.assertContains(response, "W5PAUSE was deactivated")

    def test_inactive_callsign_registration_directs_to_reactivation(self):
        self.member.is_active = False
        self.member.save(update_fields=["is_active"])
        form = MemberRegistrationForm(
            data={
                "callsign": "w5pause",
                "email": "different@example.com",
                "password1": self.password,
                "password2": self.password,
                "policy_accepted": True,
                "age_confirmed": True,
            }
        )

        self.assertFalse(form.is_valid())
        self.assertTrue(form.has_inactive_account_error)
        self.assertIn("Request reactivation", form.errors["callsign"][0])
        self.assertEqual(
            MemberProfile.objects.filter(callsign__iexact="W5PAUSE").count(),
            1,
        )

    def test_normal_member_cannot_deactivate_another_member(self):
        other = get_user_model().objects.create_user(
            username="W5OTHER",
            password=self.password,
        )
        other_profile = MemberProfile.objects.create(
            user=other,
            callsign="W5OTHER",
        )
        self.client.force_login(self.member)

        response = self.client.post(
            reverse("member_deactivate", args=[other_profile.pk])
        )

        self.assertEqual(response.status_code, 302)
        other.refresh_from_db()
        self.assertTrue(other.is_active)

    def test_staff_and_superuser_accounts_are_protected(self):
        staff = get_user_model().objects.create_user(
            username="W5STAFF2",
            password=self.password,
            is_staff=True,
        )
        staff_profile = MemberProfile.objects.create(
            user=staff,
            callsign="W5STAFF2",
        )
        self.client.force_login(self.admin)

        for route_name in ("member_deactivate", "member_reactivate"):
            response = self.client.post(
                reverse(route_name, args=[staff_profile.pk]),
                follow=True,
            )
            staff.refresh_from_db()
            self.assertTrue(staff.is_active)
            self.assertContains(response, "cannot be changed here")

        admin_profile = MemberProfile.objects.create(
            user=self.admin,
            callsign="W5ROOT",
        )
        response = self.client.get(reverse("deactivate_account"), follow=True)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        self.assertContains(response, "cannot be deactivated here")
        self.assertTrue(admin_profile.user.is_active)

    def test_permanent_delete_remains_a_separate_exceptional_action(self):
        self.client.force_login(self.admin)
        management = self.client.get(reverse("member_admin_list"))
        deletion = self.client.get(reverse("member_delete", args=[self.profile.pk]))

        self.assertContains(management, "Deactivate Member")
        self.assertContains(management, "Permanently Delete Account")
        self.assertContains(deletion, "exceptional and irreversible")
        self.assertContains(deletion, "Use account deactivation")
