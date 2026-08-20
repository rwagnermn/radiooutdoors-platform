from datetime import date
from pathlib import Path
import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import (
    Adventure,
    JournalContact,
    JournalEntry,
    Location,
    MemberProfile,
    Photo,
)


class LocationJournalUseCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.owner = user_model.objects.create_user(
            username="owner", password="test-password"
        )
        cls.other_owner = user_model.objects.create_user(
            username="other", password="test-password"
        )
        cls.staff = user_model.objects.create_user(
            username="staff", password="test-password", is_staff=True
        )
        MemberProfile.objects.create(
            user=cls.owner,
            callsign="W0OWNER",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )

    def location(self, name):
        return Location.objects.create(name=name, created_by=self.owner)

    def adventure(self, title, *, owner=None, location=None, is_public=True):
        return Adventure.objects.create(
            title=title,
            owner=owner or self.owner,
            location=location,
            is_public=is_public,
        )

    def journal(
        self,
        adventure,
        location,
        *,
        title="Journal",
        is_public=True,
        is_photo_collection=False,
    ):
        return JournalEntry.objects.create(
            adventure=adventure,
            location=location,
            title=title,
            body="Journal notes",
            is_public=is_public,
            is_adventure_photo_collection=is_photo_collection,
        )

    def uses_for(self, response, location):
        rows = {row.pk: row for row in response.context["locations"]}
        return rows[location.pk].journal_use_count

    def test_one_matching_journal_is_one_use_regardless_of_contacts_or_photos(self):
        location = self.location("One Use")
        adventure = self.adventure("One-use Adventure")
        journal = self.journal(adventure, location)
        for index in range(3):
            JournalContact.objects.create(
                journal_entry=journal,
                owner=self.owner,
                adventure=adventure,
                qso_date=date(2026, 8, 18),
                callsign=f"W0TEST{index}",
                fingerprint=f"contact-{index}",
            )
            Photo.objects.create(
                journal_entry=journal,
                image=f"unused-test-photo-{index}.jpg",
            )

        response = self.client.get(reverse("locations"))

        self.assertEqual(self.uses_for(response, location), 1)
        self.assertContains(response, '<td class="text-center">1</td>', html=True)

    def test_three_journals_in_one_adventure_are_three_uses(self):
        location = self.location("Three Uses")
        adventure = self.adventure("Three-journal Adventure")
        for index in range(3):
            self.journal(adventure, location, title=f"Journal {index}")

        response = self.client.get(reverse("locations"))

        self.assertEqual(self.uses_for(response, location), 3)

    def test_other_and_missing_journal_locations_do_not_count(self):
        location = self.location("Target Location")
        other_location = self.location("Other Location")
        adventure = self.adventure("Different-location Adventure")
        self.journal(adventure, other_location, title="Elsewhere")
        self.journal(adventure, None, title="No Location")

        response = self.client.get(reverse("locations"))

        self.assertEqual(self.uses_for(response, location), 0)
        self.assertEqual(self.uses_for(response, other_location), 1)

    def test_legacy_adventure_location_without_matching_journal_is_zero(self):
        location = self.location("Legacy Location")
        self.adventure("Legacy Adventure", location=location)

        response = self.client.get(reverse("locations"))

        self.assertEqual(self.uses_for(response, location), 0)

    def test_system_photo_collection_journal_is_not_counted(self):
        location = self.location("Photo Collection Location")
        adventure = self.adventure("Photo Collection Adventure")
        self.journal(
            adventure,
            location,
            is_photo_collection=True,
        )

        response = self.client.get(reverse("locations"))

        self.assertEqual(self.uses_for(response, location), 0)

    def test_public_private_owner_and_staff_visibility(self):
        location = self.location("Visibility Location")
        public_adventure = self.adventure("Public Adventure")
        private_adventure = self.adventure(
            "Private Adventure", is_public=False
        )
        other_private_adventure = self.adventure(
            "Other Private Adventure",
            owner=self.other_owner,
            is_public=False,
        )
        self.journal(public_adventure, location, title="Public Journal")
        self.journal(
            public_adventure,
            location,
            title="Owner Private Journal",
            is_public=False,
        )
        self.journal(private_adventure, location, title="Private Adventure Journal")
        self.journal(
            other_private_adventure,
            location,
            title="Other Owner Private Journal",
            is_public=False,
        )

        visitor_response = self.client.get(reverse("locations"))
        self.assertEqual(self.uses_for(visitor_response, location), 1)

        self.client.force_login(self.owner)
        owner_response = self.client.get(reverse("locations"))
        self.assertEqual(self.uses_for(owner_response, location), 3)

        self.client.force_login(self.other_owner)
        other_response = self.client.get(reverse("locations"))
        self.assertEqual(self.uses_for(other_response, location), 2)

        self.client.force_login(self.staff)
        staff_response = self.client.get(reverse("locations"))
        self.assertEqual(self.uses_for(staff_response, location), 4)

    def test_table_heading_is_uses_not_adventures(self):
        response = self.client.get(reverse("locations"))

        self.assertContains(response, '<th class="text-center">Uses</th>', html=True)
        self.assertNotContains(
            response,
            '<th class="text-center">Adventures</th>',
            html=True,
        )

    def test_treasure_background_asset_and_styles_are_locations_scoped(self):
        asset = (
            Path(settings.BASE_DIR)
            / "static"
            / "images"
            / "locations-treasure-map-background.png"
        )
        css = (
            Path(settings.BASE_DIR) / "static" / "css" / "style.css"
        ).read_text(encoding="utf-8")
        background_rule = re.search(
            r"body\.locations-page main\s*\{(?P<declarations>[^}]*)\}",
            css,
            re.DOTALL,
        )

        self.assertTrue(asset.is_file())
        self.assertIsNotNone(background_rule)
        self.assertIn(
            'url("../images/locations-treasure-map-background.png")',
            background_rule.group("declarations"),
        )
        self.assertEqual(
            css.count("locations-treasure-map-background.png"),
            1,
        )
        locations_css = css.split(
            "/* Locations page: compact directory over the approved treasure-map artwork. */",
            1,
        )[1]
        self.assertIn(".locations-page .locations-controls-panel", locations_css)
        self.assertIn(".locations-page .location-table-wrap", locations_css)
        self.assertNotIn("overflow: hidden", locations_css)

        expected_page_scoped_backgrounds = {
            ".locations-page .locations-controls-panel": "rgba(255, 255, 255, 0.58)",
            ".locations-page .location-table-wrap": "transparent",
            ".locations-page .location-table": "transparent",
            ".locations-page .location-table thead th": "rgba(255, 255, 255, 0.68)",
            ".locations-page .location-table tbody td": "rgba(255, 255, 255, 0.46)",
            ".locations-page .location-table tbody tr:nth-child(even) td": "rgba(255, 255, 255, 0.42)",
        }
        for selector, expected_background in expected_page_scoped_backgrounds.items():
            scoped_rule = re.search(
                rf"{re.escape(selector)}\s*\{{(?P<declarations>[^}}]*)\}}",
                locations_css,
                re.DOTALL,
            )
            self.assertIsNotNone(scoped_rule, selector)
            self.assertIn(expected_background, scoped_rule.group("declarations"))
        self.assertIn("rgba(255, 255, 255, 0.70)", locations_css)
        self.assertIn(".locations-page .location-table tbody", locations_css)
        self.assertIn(".locations-page .location-table tbody tr", locations_css)
        self.assertIn(".locations-page .location-table tbody tr[onclick]:hover td", locations_css)
        self.assertIn("backdrop-filter: none", locations_css)

        response = self.client.get(reverse("locations"))
        self.assertContains(response, 'class="interior-page locations-page"')

    def test_required_columns_permissions_and_row_navigation_remain(self):
        location = self.location("Navigable Location")
        detail_url = reverse("location_detail", args=[location.pk])

        visitor_response = self.client.get(reverse("locations"))
        for heading in ("Photo", "Location", "Type", "City", "State", "Uses"):
            if heading == "Photo":
                self.assertContains(visitor_response, '<th aria-label="Photo"></th>', html=True)
            elif heading == "Uses":
                self.assertContains(
                    visitor_response,
                    '<th class="text-center">Uses</th>',
                    html=True,
                )
            else:
                self.assertContains(visitor_response, f"<th>{heading}</th>", html=True)
        self.assertNotContains(visitor_response, "Add New Location")
        self.assertContains(visitor_response, f"window.location='{detail_url}'")
        self.assertContains(visitor_response, f'href="{detail_url}"')

        self.client.force_login(self.owner)
        owner_response = self.client.get(reverse("locations"))
        self.assertContains(owner_response, "Add New Location")

        self.client.force_login(self.staff)
        staff_response = self.client.get(reverse("locations"))
        self.assertContains(
            staff_response,
            '<th class="staff-id-column">ID</th>',
            html=True,
        )
