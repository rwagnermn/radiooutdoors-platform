from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from adventures.forms import AdventureForm, JournalEntryForm
from core.models import Adventure, JournalEntry, Location, MemberProfile, OperatingLocation
from core.qrz_service import QRZResult


class OperatingCallsignTests(TestCase):
    def setUp(self):
        self.password = "CedarRidgeExpedition!942"
        self.owner = get_user_model().objects.create_user(
            "W5OWNER", password=self.password
        )
        MemberProfile.objects.create(
            user=self.owner,
            callsign="W5OWNER",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.other = get_user_model().objects.create_user("K0OTHER")
        MemberProfile.objects.create(
            user=self.other,
            callsign="K0OTHER",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.location = Location.objects.create(name="Operating Test Park")
        self.position = OperatingLocation.objects.create(
            location=self.location, name="North Field"
        )

    def form_data(self, callsign, callsign_type):
        return {
            "title": f"{callsign_type} Adventure",
            "is_public": True,
            "operating_callsign": callsign,
            "operating_callsign_type": callsign_type,
            "operating_identity_name": "Oregon State",
            "operating_callsign_explanation": "Authorized event operation.",
            "operating_callsign_url": "https://example.org/event",
            "operating_start_date": "2026-08-01",
            "operating_end_date": "2026-08-08",
            "location": self.location.pk,
            "operating_location": self.position.pk,
        }

    def test_new_adventure_defaults_to_members_personal_callsign(self):
        form = AdventureForm(user=self.owner)
        self.assertEqual(form.initial["operating_callsign"], "W5OWNER")
        self.assertEqual(
            form.fields["operating_callsign_type"].initial,
            Adventure.OperatingCallsignType.PERSONAL,
        )
        adventure = Adventure.objects.create(owner=self.owner, title="Legacy-style")
        self.assertEqual(adventure.operating_callsign, "W5OWNER")

    def test_all_authorized_callsign_types_save_without_member_accounts(self):
        cases = (
            (Adventure.OperatingCallsignType.PERSONAL, "W5OWNER"),
            (Adventure.OperatingCallsignType.SPECIAL_EVENT, "W7O"),
            (Adventure.OperatingCallsignType.CLUB, "W5CLUB"),
            (Adventure.OperatingCallsignType.CONTEST, "K5CONTEST"),
            (Adventure.OperatingCallsignType.PORTABLE_REGIONAL, "W5OWNER/7"),
            (Adventure.OperatingCallsignType.OTHER, "N0EVENT"),
        )
        for callsign_type, callsign in cases:
            with self.subTest(callsign_type=callsign_type):
                form = AdventureForm(self.form_data(callsign, callsign_type), user=self.owner)
                self.assertTrue(form.is_valid(), form.errors)
                adventure = form.save(commit=False)
                adventure.owner = self.owner
                adventure.save()
                self.assertEqual(adventure.operating_callsign, callsign)
                self.assertEqual(adventure.operating_callsign_type, callsign_type)
                self.assertFalse(
                    get_user_model().objects.filter(username=callsign).exclude(pk=self.owner.pk).exists()
                )

    def test_multiple_members_can_use_same_event_callsign(self):
        first = Adventure.objects.create(
            owner=self.owner,
            title="First W7O Adventure",
            operating_callsign="w7o",
            operating_callsign_type=Adventure.OperatingCallsignType.SPECIAL_EVENT,
        )
        second = Adventure.objects.create(
            owner=self.other,
            title="Second W7O Adventure",
            operating_callsign="W7O",
            operating_callsign_type=Adventure.OperatingCallsignType.SPECIAL_EVENT,
        )
        self.assertEqual(first.operating_callsign, second.operating_callsign)
        self.assertNotEqual(first.owner, second.owner)

    def test_adventure_displays_operating_and_managing_identities(self):
        adventure = Adventure.objects.create(
            owner=self.owner,
            title="Oregon State Event",
            operating_callsign="W7O",
            operating_callsign_type=Adventure.OperatingCallsignType.SPECIAL_EVENT,
            operating_identity_name="Oregon State",
            operating_callsign_url="https://example.org/event",
            operating_start_date=date(2026, 8, 1),
            operating_end_date=date(2026, 8, 8),
        )
        response = self.client.get(adventure.get_absolute_url())
        self.assertContains(response, "Operator:</strong> W7O")
        self.assertContains(response, "Managed by:</strong> W5OWNER")

    def test_journal_defaults_to_adventure_callsign_and_allows_another(self):
        adventure = Adventure.objects.create(
            owner=self.owner,
            title="Journal Callsign",
            operating_callsign="W7O",
            operating_callsign_type=Adventure.OperatingCallsignType.SPECIAL_EVENT,
        )
        form = JournalEntryForm(adventure=adventure)
        self.assertEqual(form.initial["operating_callsign"], "W7O")
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("add_journal_entry", kwargs={"slug": adventure.slug}),
            {
                "entry_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
                "title": "Alternate operator",
                "body": "A contact made under another authorized call.",
                "operating_callsign": "K7ALT",
                "location": self.location.pk,
                "location_name": self.location.name,
                "latitude": "44.100000",
                "longitude": "-93.200000",
                "journal_visibility_present": "1",
                "is_public": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        entry = JournalEntry.objects.get(adventure=adventure)
        self.assertEqual(entry.operating_callsign, "K7ALT")
        detail = self.client.get(reverse("journal_entry_detail", args=[entry.pk]))
        self.assertContains(detail, "Operator:</strong> K7ALT")

    def test_operating_identity_does_not_change_owner_permissions(self):
        adventure = Adventure.objects.create(
            owner=self.owner, title="Owned Adventure", operating_callsign="W7O"
        )
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.get(reverse("edit_adventure", args=[adventure.slug])).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("add_journal_entry", args=[adventure.slug])).status_code,
            403,
        )


class QRZOrganizationIdentityTests(TestCase):
    @patch("core.account_views.lookup_callsign")
    def test_non_person_qrz_record_uses_callsign_for_welcome(self, lookup):
        lookup.return_value = QRZResult(
            callsign="W7O",
            first_name="Oregon State",
            last_name="Special Event",
            country="United States",
            record_type="",
        )
        response = self.client.post(
            reverse("register"),
            {
                "callsign": "W7O",
                "email": "w7o-test@example.com",
                "password1": "CedarRidgeExpedition!942",
                "password2": "CedarRidgeExpedition!942",
                "policy_accepted": "on",
                "age_confirmed": "on",
            },
        )
        self.assertRedirects(response, reverse("member_welcome"))
        user = get_user_model().objects.get(username="W7O")
        self.assertEqual(user.first_name, "")
        self.assertEqual(user.member_profile.qrz_first_name, "")
        welcome = self.client.get(reverse("member_welcome"))
        self.assertContains(welcome, "Welcome to Radio Outdoors, W7O!")
        self.assertNotContains(welcome, "Welcome to Radio Outdoors, Oregon State!")
