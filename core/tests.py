from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch
from io import BytesIO, StringIO
from tempfile import TemporaryDirectory

# Create your tests here.


from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from .auth import is_verified_member
from .form_validation import REQUIRED_SAVE_MESSAGE
from .models import (
    Adventure,
    BlockedDomain,
    Comment,
    FollowerInvitation,
    FollowRelationship,
    JournalContact,
    JournalEntry,
    Location,
    MemberProfile,
    OperatingLocation,
    Photo,
)
from .qrz_service import (
    QRZConfigurationError,
    QRZError,
    QRZNotFoundError,
    QRZResult,
    QRZUnavailableError,
)


class AdventureDisplayStatusTests(TestCase):
    def setUp(self):
        self.operator = get_user_model().objects.create_user(
            username="W5TEST",
            password="test-password",
        )

    def test_active_adventure_is_open(self):
        adventure = Adventure.objects.create(
            owner=self.operator,
            title="Open Adventure",
        )
        self.assertEqual(adventure.display_status_key, "active")
        self.assertEqual(adventure.display_status_label, "Active")
        self.assertEqual(adventure.get_status_display(), "Active")

    def test_completed_adventure_is_complete(self):
        adventure = Adventure.objects.create(
            owner=self.operator,
            title="Completed Adventure",
            status=Adventure.Status.COMPLETED,
        )
        self.assertEqual(adventure.display_status_key, "complete")
        self.assertEqual(adventure.display_status_label, "Complete")
        self.assertEqual(adventure.get_status_display(), "Complete")


class MapExplorerOpenAdventureTests(TestCase):
    def test_main_map_uses_compact_scoped_heading_and_toolbar(self):
        response = self.client.get(reverse("map_explorer"))

        self.assertContains(response, "radio-map-heading-row")
        self.assertContains(response, "radio-map-heading-copy")
        self.assertContains(response, "radio-map-compact-toolbar")
        self.assertContains(response, "radio-map-toolbar-actions")
        self.assertContains(response, "Radio Outdoors Map")
        self.assertContains(response, "Map Filters")
        self.assertContains(response, "Map Legend")

    def test_main_map_compaction_is_responsive_and_does_not_target_embedded_maps(self):
        css = (settings.BASE_DIR / "static" / "css" / "style.css").read_text(
            encoding="utf-8"
        )

        self.assertIn(".map-page-content .radio-map-compact-toolbar", css)
        self.assertIn("flex-wrap:wrap", css)
        self.assertIn("@media(max-width:700px)", css)
        self.assertIn(".map-page-content .radio-map-toolbar-actions{display:grid", css)
        self.assertIn(".radio-outdoors-map{\n    width:100%;\n    height:720px", css)
        self.assertNotIn(".embedded-detail-map-layout .radio-map-compact-toolbar", css)

    def test_open_adventure_without_operating_position_gets_yellow_location_pin(self):
        operator = get_user_model().objects.create_user(
            username="W5MAP",
            password="test-password",
        )
        location = Location.objects.create(
            name="Map Test Park",
            latitude="44.977800",
            longitude="-93.265000",
        )
        Adventure.objects.create(
            owner=operator,
            title="Unassigned Current Adventure",
            location=location,
            status=Adventure.Status.ACTIVE,
            is_public=True,
        )

        response = self.client.get("/map/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["map_points"]), 1)
        point = response.context["map_points"][0]
        self.assertEqual(point["marker_type"], "location")
        self.assertTrue(point["has_open_adventure"])
        self.assertEqual(point["coordinate_source"], "location")

    def test_coordinate_bearing_location_without_activity_gets_default_pin(self):
        location = Location.objects.create(
            name="Quiet Map Location",
            latitude="0.000000",
            longitude="-93.265000",
        )

        response = self.client.get(reverse("map_explorer"))

        points = response.context["map_points"]
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["location_id"], location.pk)
        self.assertEqual(points[0]["marker_type"], "location")
        self.assertFalse(points[0]["has_open_adventure"])
        self.assertFalse(points[0]["has_operating_advisory"])
        self.assertEqual(points[0]["latitude"], 0.0)

    def test_advisory_location_is_included_without_an_adventure(self):
        location = Location.objects.create(
            name="Advisory Map Location",
            latitude="44.000000",
            longitude="-94.000000",
            has_operating_advisory=True,
            operating_advisory="Road access is limited.",
        )

        response = self.client.get(reverse("map_explorer"))

        point = response.context["map_points"][0]
        self.assertEqual(point["location_id"], location.pk)
        self.assertTrue(point["has_operating_advisory"])
        self.assertEqual(point["operating_advisory"], "Road access is limited.")

    def test_advisory_popup_renders_current_text_safely_in_the_required_position(self):
        location = Location.objects.create(
            name="Airport Operating Site",
            latitude="44.000000",
            longitude="-94.000000",
            has_operating_advisory=True,
            operating_advisory='First line.\nSecond <script>alert("x")</script> line.',
        )

        response = self.client.get(reverse("map_explorer"))
        point = response.context["map_points"][0]
        html = response.content.decode()

        self.assertEqual(point["location_id"], location.pk)
        self.assertEqual(
            point["operating_advisory"],
            'First line.\nSecond <script>alert("x")</script> line.',
        )
        self.assertContains(response, "radio-map-popup-advisory")
        self.assertContains(response, "OPERATING ADVISORY")
        self.assertContains(response, "escapeMapText(advisoryText).replace")
        self.assertNotIn('<script>alert("x")</script>', html)
        self.assertLess(html.index("+ advisory"), html.index("radio-map-popup-count"))

        location.operating_advisory = "Updated advisory text."
        location.save(update_fields=["operating_advisory"])
        updated_response = self.client.get(reverse("map_explorer"))
        self.assertEqual(
            updated_response.context["map_points"][0]["operating_advisory"],
            "Updated advisory text.",
        )

    def test_advisory_popup_requires_both_advisory_marker_and_nonblank_text(self):
        ordinary = Location.objects.create(
            name="Ordinary Location",
            latitude="44.000000",
            longitude="-94.000000",
            operating_advisory="Text on an ordinary pin is not displayed.",
        )
        blank_advisory = Location.objects.create(
            name="Blank Advisory Location",
            latitude="45.000000",
            longitude="-95.000000",
            has_operating_advisory=True,
            operating_advisory="   ",
        )

        response = self.client.get(reverse("map_explorer"))
        points = {
            point["location_id"]: point for point in response.context["map_points"]
        }

        self.assertFalse(points[ordinary.pk]["has_operating_advisory"])
        self.assertTrue(points[blank_advisory.pk]["has_operating_advisory"])
        self.assertContains(
            response,
            "point.has_operating_advisory && advisoryText",
        )

    def test_advisory_popup_is_vertically_scrollable_without_horizontal_overflow(self):
        css = (settings.BASE_DIR / "static" / "css" / "style.css").read_text(
            encoding="utf-8"
        )

        popup_rule = css[css.index(".radio-map-popup-card{") :]
        self.assertIn("max-height:min(520px,calc(100vh - 90px))", popup_rule)
        self.assertIn("overflow-x:hidden", popup_rule)
        self.assertIn("overflow-y:auto", popup_rule)
        self.assertIn(".radio-map-popup-advisory{", css)
        self.assertIn("overflow-wrap:anywhere", css)

    def test_location_without_coordinates_is_excluded(self):
        Location.objects.create(name="No Coordinates")

        response = self.client.get(reverse("map_explorer"))

        self.assertEqual(response.context["map_points"], [])

    def test_operating_position_does_not_create_a_second_public_pin(self):
        location = Location.objects.create(
            name="Position Test Location",
            latitude="44.000000",
            longitude="-94.000000",
        )
        position = OperatingLocation.objects.create(
            location=location,
            name="Picnic Shelter",
            latitude="44.100000",
            longitude="-94.100000",
        )

        response = self.client.get(reverse("map_explorer"))

        points = response.context["map_points"]
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["marker_type"], "location")
        self.assertEqual(points[0]["location_id"], location.pk)

    def test_legacy_location_uses_display_only_coordinate_fallback(self):
        location = Location.objects.create(name="Legacy Position Location")
        OperatingLocation.objects.create(
            location=location, name="Historical Position",
            latitude="44.100000", longitude="-94.100000",
        )
        response = self.client.get(reverse("map_explorer"))
        point = response.context["map_points"][0]
        self.assertEqual(point["location_id"], location.pk)
        self.assertEqual(point["coordinate_source"], "legacy_operating_position_fallback")
        location.refresh_from_db()
        self.assertIsNone(location.latitude)

    def test_map_template_distinguishes_location_and_operating_filters(self):
        response = self.client.get(reverse("map_explorer"))

        self.assertContains(response, "Location</span>")
        self.assertContains(response, 'id="show-location-pins" checked')
        self.assertNotContains(response, 'id="show-operating-pins"')
        self.assertContains(response, 'id="show-open-pins" checked')
        self.assertContains(response, "Operating Advisories — Always shown")
        self.assertNotContains(response, "Open Adventures Only")
        self.assertContains(response, "if (record.point.has_operating_advisory)")
        self.assertContains(response, "Get Directions to Pin")
        self.assertContains(response, "Copy Coordinates")
        self.assertContains(response, "Find Nearest Mapped Address")
        self.assertContains(response, "nearestAddressCache")


class SupportPageTests(TestCase):
    def test_support_page_is_informational_and_payment_controls_are_disabled(self):
        response = self.client.get("/support/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Support Radio Outdoors")
        self.assertContains(response, "Make a One-Time Contribution")
        self.assertContains(response, "Become a Sustaining Supporter")
        self.assertContains(response, "Help Cover Infrastructure")
        self.assertContains(response, "Other Ways to Help")
        self.assertContains(response, "Payment Setup Pending")
        self.assertContains(response, '<button type="button" disabled', count=12)
        self.assertNotContains(response, "checkout session")
        self.assertNotContains(response, "stripe.com")
        self.assertNotContains(response, "paypal.com/sdk")


class AdventureBookTerminologyTests(TestCase):
    def test_public_navigation_uses_adventure_book(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, ">Adventure Book</a>")
        self.assertContains(response, "Explore The Adventure Book")
        self.assertNotContains(response, "Explore Adventures")
        self.assertNotContains(response, "Explore Locations")

    def test_public_collection_page_identifies_public_adventures_mode(self):
        response = self.client.get(reverse("all_adventures"))
        self.assertContains(response, "<title>Public Adventures | Radio Outdoors</title>")
        self.assertContains(response, "<h1>Public Adventures</h1>")
        self.assertContains(
            response,
            "Adventures shared publicly by Radio Outdoors members.",
        )
        self.assertContains(
            response,
            f'<a href="{reverse("all_adventures")}" aria-current="page">Public Adventures</a>',
        )
        self.assertContains(response, "adventure-list-page")
        self.assertContains(response, "adventure-panel-list")
        self.assertContains(response, 'placeholder="Search Adventures"')
        self.assertNotContains(response, "View All Public Adventures")
        self.assertNotContains(response, "View My Adventures")
        self.assertContains(response, "adventure-book-panel-filters")
        self.assertContains(response, "adventure-book-apply")

    def test_public_collection_summarizes_contacts_instead_of_comments(self):
        owner = get_user_model().objects.create_user(
            username="W5COUNTS",
            password="test-password",
        )
        MemberProfile.objects.create(
            user=owner,
            callsign="W5COUNTS",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        with_contacts = Adventure.objects.create(
            owner=owner,
            title="Adventure With Contacts",
            is_public=True,
        )
        without_contacts = Adventure.objects.create(
            owner=owner,
            title="Adventure Without Contacts",
            is_public=True,
        )
        entry = JournalEntry.objects.create(
            adventure=with_contacts,
            title="Contact Journal",
            body="Journal notes",
        )
        JournalContact.objects.create(
            journal_entry=entry,
            qso_date=timezone.localdate(),
            callsign="W1FIRST",
            fingerprint="first-contact",
        )
        JournalContact.objects.create(
            journal_entry=entry,
            qso_date=timezone.localdate(),
            callsign="W2SECOND",
            fingerprint="second-contact",
        )
        JournalContact.objects.bulk_create(
            [
                JournalContact(
                    journal_entry=entry,
                    qso_date=timezone.localdate(),
                    callsign=f"W3{i:04d}",
                    fingerprint=f"contact-{i}",
                )
                for i in range(1780)
            ]
        )
        Comment.objects.create(
            adventure=with_contacts,
            operator=owner,
            body="This comment must not affect the Contact count.",
        )

        response = self.client.get(reverse("all_adventures"))
        adventures = {item.pk: item for item in response.context["adventures"]}

        self.assertContains(
            response,
            '<div><dt>Contacts</dt><dd>1782</dd></div>',
        )
        self.assertContains(
            response,
            '<dl class="adventure-panel-counts">',
        )
        self.assertNotContains(response, '<th class="center-column">Comments</th>')
        self.assertTrue(hasattr(adventures[with_contacts.pk], "contact_count"))
        self.assertFalse(hasattr(adventures[with_contacts.pk], "comment_count"))
        self.assertEqual(adventures[with_contacts.pk].contact_count, 1782)
        self.assertEqual(adventures[with_contacts.pk].journal_count, 1)
        self.assertEqual(adventures[with_contacts.pk].photo_count, 0)
        self.assertEqual(adventures[without_contacts.pk].contact_count, 0)

        self.client.force_login(owner)
        response = self.client.get(reverse("my_adventures"))
        adventures = {item.pk: item for item in response.context["adventures"]}
        self.assertContains(
            response,
            '<div><dt>Contacts</dt><dd>1782</dd></div>',
        )
        self.assertContains(
            response,
            '<dl class="adventure-panel-counts">',
        )
        self.assertNotContains(response, '<th class="center-column">Comments</th>')
        self.assertEqual(adventures[with_contacts.pk].contact_count, 1782)
        self.assertEqual(adventures[without_contacts.pk].contact_count, 0)

    def test_verified_member_sees_only_the_opposite_adventure_view(self):
        user = get_user_model().objects.create_user(
            username="W5BOOK",
            password="StrongPass!942",
        )
        MemberProfile.objects.create(
            user=user,
            callsign="W5BOOK",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.client.force_login(user)
        response = self.client.get(reverse("all_adventures"))
        self.assertContains(response, ">My Adventures</a>")
        self.assertContains(response, reverse("my_adventures"))
        self.assertNotContains(response, "View All Public Adventures")
        self.assertContains(response, '>Public Adventures</a>')

        response = self.client.get(reverse("my_adventures"))
        self.assertContains(response, ">Public Adventures</a>")
        self.assertContains(response, reverse("all_adventures"))
        self.assertContains(
            response,
            f'<a href="{reverse("my_adventures")}" aria-current="page">My Adventures</a>',
        )
        self.assertContains(response, "<h1>My Adventures</h1>")
        self.assertContains(response, "Adventures created and managed by your signed-in account.")
        self.assertContains(response, "adventure-list-page")
        self.assertContains(response, "adventure-panel-list")


class BrandHierarchyTests(TestCase):
    def test_home_uses_concise_product_name_and_tagline(self):
        response = self.client.get(reverse("home"))
        self.assertContains(
            response,
            '<p class="hero-product-name">Radio Outdoors™</p>',
        )
        self.assertContains(
            response,
            '<p class="hero-story">Your storybook of ham radio adventures.</p>',
        )
        self.assertContains(response, "Explore The Adventure Book")
        self.assertContains(response, "Join Radio Outdoors")
        self.assertNotContains(response, "Explore Locations")
        self.assertNotContains(response, "Some contacts are measured")

    def test_public_member_profile_presents_only_public_adventure_book(self):
        user = get_user_model().objects.create_user(
            "W5STORY",
            first_name="Rick",
        )
        MemberProfile.objects.create(
            user=user,
            callsign="W5STORY",
            display_name="Rick",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        public_adventure = Adventure.objects.create(
            owner=user,
            title="Public Story Adventure",
            is_public=True,
        )
        second_public_adventure = Adventure.objects.create(
            owner=user,
            title="Second Public Story Adventure",
            is_public=True,
        )
        Adventure.objects.create(
            owner=user,
            title="Private Story Adventure",
            is_public=False,
        )

        response = self.client.get(reverse("member_detail", args=["W5STORY"]))
        self.assertContains(response, "Rick's Adventure Book")
        self.assertContains(response, "<span>Adventures</span>")
        self.assertContains(response, public_adventure.title)
        self.assertContains(response, second_public_adventure.title)
        self.assertNotContains(response, "Private Story Adventure")
        self.assertContains(response, "View Adventure", count=2)
        self.assertContains(response, "member-adventure-view-action", count=2)

    def test_trademark_marking_is_selective(self):
        home = self.client.get(reverse("home"))
        self.assertContains(home, '<span class="logo-trademark" aria-hidden="true">™</span>')
        self.assertContains(home, '<p class="hero-product-name">Radio Outdoors™</p>')
        self.assertContains(home, "<h3>Radio Outdoors™</h3>")

        about = self.client.get(reverse("about"))
        self.assertContains(
            about,
            "<h1>Radio Outdoors™ preserves the stories behind outdoor amateur radio Adventures.</h1>",
        )
        for response in [home, about]:
            self.assertNotContains(response, "®")
            self.assertNotContains(response, "Adventure Book™")

    def test_member_adventure_book_heading_falls_back_to_callsign(self):
        user = get_user_model().objects.create_user("W0NONAME")
        MemberProfile.objects.create(
            user=user,
            callsign="W0NONAME",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        response = self.client.get(reverse("member_detail", args=["W0NONAME"]))
        self.assertContains(response, "W0NONAME's Adventure Book")

    def test_management_and_help_language_remain_distinct(self):
        user = get_user_model().objects.create_user("W5MANAGE")
        MemberProfile.objects.create(
            user=user,
            callsign="W5MANAGE",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.client.force_login(user)
        management = self.client.get(reverse("my_adventures"))
        self.assertContains(management, "<h1>My Adventures</h1>")
        self.assertNotContains(management, "<h1>My Adventure Book</h1>")

        help_page = self.client.get(reverse("help_center"))
        self.assertContains(
            help_page,
            "Radio Outdoors is your storybook of ham radio adventures.",
        )


class LoginRedirectTests(TestCase):
    password = "StrongPass!942"

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="W5LOGIN",
            password=self.password,
        )
        MemberProfile.objects.create(
            user=self.user,
            callsign="W5LOGIN",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )

    def login_data(self, **overrides):
        data = {"username": self.user.username, "password": self.password}
        data.update(overrides)
        return data

    def test_header_sign_in_has_no_next_and_uses_adventure_book_default(self):
        header = self.client.get(reverse("home"))
        self.assertContains(header, f'href="{reverse("login")}"')
        self.assertNotContains(header, f'href="{reverse("login")}?next=')

        response = self.client.post(reverse("login"), self.login_data())
        self.assertRedirects(response, reverse("my_adventures"))
        destination = self.client.get(reverse("my_adventures"))
        self.assertContains(destination, "W5LOGIN")
        self.assertContains(destination, "Add Adventure")

    def test_direct_login_uses_adventure_book_default(self):
        response = self.client.post(reverse("login"), self.login_data())
        self.assertRedirects(response, reverse("my_adventures"))

    def test_protected_page_login_preserves_valid_next(self):
        protected_url = reverse("add_adventure")
        redirect_response = self.client.get(protected_url)
        self.assertRedirects(
            redirect_response,
            f'{reverse("login")}?next={protected_url}',
        )

        response = self.client.post(
            reverse("login"),
            self.login_data(next=protected_url),
        )
        self.assertRedirects(response, protected_url)

    def test_external_next_falls_back_to_adventure_book(self):
        response = self.client.post(
            reverse("login"),
            self.login_data(next="https://evil.example/steal"),
        )
        self.assertRedirects(response, reverse("my_adventures"))


class DevelopmentDemoDataTests(TestCase):
    @override_settings(DEBUG=True)
    def test_generator_is_repeatable_realistic_and_safely_removable(self):
        real_user = get_user_model().objects.create_user("real-local-user")
        real_adventure = Adventure.objects.create(
            owner=real_user,
            title="Real local Adventure",
        )

        with TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            first_output = StringIO()
            call_command("create_demo_data", stdout=first_output)
            call_command("create_demo_data", stdout=StringIO())

            demo_profiles = MemberProfile.objects.filter(
                user__username__startswith="demo_"
            ).select_related("user")
            self.assertEqual(demo_profiles.count(), 6)
            for profile in demo_profiles:
                with self.subTest(callsign=profile.callsign):
                    self.assertEqual(profile.user.adventures.count(), 10)
                    self.assertEqual(
                        JournalEntry.objects.filter(
                            adventure__owner=profile.user
                        ).count(),
                        15,
                    )
                    self.assertEqual(
                        profile.verification_method,
                        MemberProfile.VerificationMethod.DEVELOPMENT,
                    )
                    self.assertTrue(profile.callsign_verified)
                    self.assertGreater(
                        profile.user.adventures.filter(is_public=True).count(),
                        profile.user.adventures.filter(is_public=False).count(),
                    )

            self.assertEqual(
                Adventure.objects.filter(
                    owner__username__startswith="demo_"
                ).count(),
                60,
            )
            self.assertEqual(
                JournalEntry.objects.filter(
                    adventure__owner__username__startswith="demo_"
                ).count(),
                90,
            )
            self.assertEqual(
                Photo.objects.filter(
                    journal_entry__adventure__owner__username__startswith="demo_"
                ).count(),
                18,
            )
            self.assertTrue(
                Adventure.objects.filter(title__contains="Field Day").exists()
            )
            self.assertTrue(
                JournalEntry.objects.filter(
                    body__contains="safe coax routing"
                ).exists()
            )

            call_command("remove_demo_data", stdout=StringIO())

        self.assertFalse(
            get_user_model().objects.filter(username__startswith="demo_").exists()
        )
        self.assertTrue(
            Adventure.objects.filter(pk=real_adventure.pk, owner=real_user).exists()
        )

    @override_settings(DEBUG=False)
    def test_demo_commands_refuse_to_run_outside_development(self):
        for command in ["create_demo_data", "remove_demo_data"]:
            with self.subTest(command=command):
                with self.assertRaises(CommandError):
                    call_command(command, stdout=StringIO())


class MemberRegistrationTests(TestCase):
    password = "StrongPass!942"

    def registration_data(self, **overrides):
        data = {
            "callsign": "w5new",
            "email": "operator@example.com",
            "password1": self.password,
            "password2": self.password,
            "policy_accepted": "on",
            "age_confirmed": "on",
        }
        data.update(overrides)
        return data

    def qrz_result(self, callsign="W5NEW"):
        return QRZResult(
            callsign=callsign,
            first_name="Casey",
            last_name="Operator",
            city="Austin",
            state="TX",
            country="United States",
            grid="EM10",
            license_class="General",
            expires="2032-01-01",
        )

    def test_each_registration_field_has_one_explicit_required_indicator(self):
        response = self.client.get(reverse("register"))
        self.assertContains(response, 'class="required-field-text"', count=4)

    @patch("core.account_views.lookup_callsign")
    def test_valid_qrz_registration_creates_verified_member(self, lookup):
        lookup.return_value = self.qrz_result()
        response = self.client.post(reverse("register"), self.registration_data())

        self.assertRedirects(response, reverse("member_welcome"))
        user = get_user_model().objects.get(email="operator@example.com")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        profile = user.member_profile
        self.assertEqual(user.username, "W5NEW")
        self.assertEqual(profile.callsign, "W5NEW")
        self.assertTrue(profile.callsign_verified)
        self.assertEqual(
            profile.verification_method,
            MemberProfile.VerificationMethod.QRZ,
        )
        self.assertIsNotNone(profile.qrz_verified_at)
        self.assertFalse(profile.email_visible_to_members)
        self.assertEqual(profile.qrz_first_name, "Casey")
        self.assertEqual(profile.qrz_city, "Austin")
        self.assertEqual(profile.qrz_grid, "EM10")
        lookup.assert_called_once_with("W5NEW")

        destination = self.client.get(reverse("my_adventures"))
        self.assertContains(destination, "W5NEW - Casey")
        self.assertContains(destination, ">Add Adventure</a>")

        welcome = self.client.get(reverse("member_welcome"))
        self.assertContains(welcome, "Welcome to Radio Outdoors")
        self.assertContains(welcome, reverse("add_adventure"))
        self.assertContains(welcome, reverse("locations"))
        self.assertContains(welcome, reverse("create_location"))
        self.assertContains(welcome, reverse("my_adventures"))

    @patch("core.account_views.lookup_callsign")
    def test_invalid_callsign_creates_nothing(self, lookup):
        lookup.side_effect = QRZNotFoundError("not found")
        response = self.client.post(reverse("register"), self.registration_data())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Callsign not found")
        self.assertFalse(get_user_model().objects.exists())

    @patch("core.account_views.lookup_callsign")
    def test_qrz_unavailable_creates_nothing(self, lookup):
        lookup.side_effect = QRZUnavailableError("timeout")
        response = self.client.post(reverse("register"), self.registration_data())
        self.assertContains(response, "temporarily unavailable")
        self.assertFalse(get_user_model().objects.exists())

    def test_duplicate_callsign_is_rejected_before_qrz(self):
        user = get_user_model().objects.create_user("W5NEW")
        MemberProfile.objects.create(
            user=user,
            callsign="W5NEW",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        response = self.client.post(reverse("register"), self.registration_data())
        self.assertContains(response, "already registered")

    def test_duplicate_email_is_rejected(self):
        get_user_model().objects.create_user(
            "someone", email="operator@example.com"
        )
        response = self.client.post(reverse("register"), self.registration_data())
        message = "That email address is already connected to a Radio Outdoors account. Log in or use Forgot callsign or password."
        self.assertContains(response, message, count=2)
        self.assertContains(response, reverse("login"))
        self.assertContains(response, reverse("account_recovery"))
        self.assertContains(response, "save-error-summary")

    @patch("core.account_views.lookup_callsign")
    def test_international_qrz_callsign_is_accepted(self, lookup):
        lookup.return_value = QRZResult(
            callsign="DL1ABC",
            first_name="Anna",
            last_name="Funk",
            city="Berlin",
            state="",
            country="Germany",
            grid="JO62",
            license_class="A",
            expires="2031-12-31",
        )
        response = self.client.post(
            reverse("register"),
            self.registration_data(callsign="dl1abc"),
        )
        self.assertRedirects(response, reverse("member_welcome"))
        profile = MemberProfile.objects.get(callsign="DL1ABC")
        self.assertEqual(profile.home_country, "Germany")
        self.assertTrue(profile.callsign_verified)
        lookup.assert_called_once_with("DL1ABC")

    def test_password_mismatch_preserves_identity_fields_and_clears_passwords(self):
        response = self.client.post(
            reverse("register"),
            self.registration_data(password2="DifferentPass!742"),
        )
        self.assertContains(response, "The two password fields didn’t match.")
        self.assertContains(response, 'value="w5new"')
        self.assertContains(response, 'value="operator@example.com"')
        self.assertNotContains(response, self.password)
        self.assertNotContains(response, "DifferentPass!742")

    def test_weak_password_is_listed_in_summary_and_below_field(self):
        response = self.client.post(
            reverse("register"),
            self.registration_data(password1="password", password2="password"),
        )
        self.assertContains(response, "This password is too common.", count=2)
        self.assertContains(response, 'class="field-error-list"')

    def test_duplicate_callsign_has_summary_and_field_error(self):
        user = get_user_model().objects.create_user("W5NEW")
        MemberProfile.objects.create(
            user=user,
            callsign="W5NEW",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        response = self.client.post(reverse("register"), self.registration_data())
        self.assertContains(response, "That callsign is already registered.", count=2)
        self.assertContains(response, "save-error-summary")

    def test_visible_error_summary_is_focusable_and_lists_all_errors(self):
        response = self.client.post(
            reverse("register"),
            {"callsign": "", "email": "invalid", "password1": "", "password2": ""},
        )
        self.assertContains(
            response,
            REQUIRED_SAVE_MESSAGE,
        )
        self.assertContains(response, 'role="alert"')
        self.assertContains(response, 'tabindex="-1"')
        self.assertContains(response, "js/registration-errors.js")
        self.assertContains(response, "Callsign:")
        self.assertContains(response, "Email address:")

    @patch("core.account_views.lookup_callsign")
    def test_qrz_failures_are_clearly_distinguished(self, lookup):
        cases = [
            (QRZNotFoundError("missing"), "Callsign not found"),
            (QRZUnavailableError("timeout"), "QRZ is temporarily unavailable"),
            (
                QRZConfigurationError("missing credentials"),
                "QRZ configuration or connection failure",
            ),
            (QRZError("connection rejected"), "QRZ configuration or connection failure"),
        ]
        for error, expected in cases:
            with self.subTest(error=type(error).__name__):
                lookup.side_effect = error
                response = self.client.post(
                    reverse("register"), self.registration_data()
                )
                self.assertContains(response, expected)
                self.assertContains(response, "save-error-summary")
                self.assertFalse(get_user_model().objects.exists())

    def test_blocked_email_domain_is_rejected(self):
        BlockedDomain.objects.create(domain="example.com")
        response = self.client.post(reverse("register"), self.registration_data())
        self.assertContains(response, "email domain are not accepted")

    @patch("core.account_views.lookup_callsign")
    def test_verified_member_can_publish(self, lookup):
        lookup.return_value = self.qrz_result()
        self.client.post(reverse("register"), self.registration_data())
        location = Location.objects.create(name="Registration Park")
        position = OperatingLocation.objects.create(
            location=location, name="Picnic Table"
        )
        response = self.client.post(
            reverse("add_adventure"),
            {
                "title": "Verified Member Adventure",
                "location": location.pk,
                "operating_location": position.pk,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Adventure.objects.filter(title="Verified Member Adventure").exists()
        )


class FollowerRegistrationTests(TestCase):
    password = "StrongPass!942"

    def setUp(self):
        self.member_user = get_user_model().objects.create_user(
            "W5HOST", email="host@example.com", password=self.password
        )
        self.member = MemberProfile.objects.create(
            user=self.member_user,
            callsign="W5HOST",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.invitation = FollowerInvitation.objects.create(
            member=self.member,
            name="Invited Person",
            email="follower@example.com",
        )

    def follower_data(self, email="follower@example.com"):
        return {
            "email": email,
            "password1": self.password,
            "password2": self.password,
            "policy_accepted": "on",
            "age_confirmed": "on",
        }

    def test_valid_invitation_creates_follower_without_profile(self):
        response = self.client.post(
            reverse("follower_register", kwargs={"token": self.invitation.token}),
            self.follower_data(),
        )
        self.assertEqual(response.status_code, 302)
        follower = get_user_model().objects.get(email="follower@example.com")
        self.assertFalse(hasattr(follower, "member_profile"))
        relationship = FollowRelationship.objects.get(follower=follower)
        self.assertEqual(relationship.status, FollowRelationship.Status.APPROVED)
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.status, FollowerInvitation.Status.ACCEPTED)

    def test_invalid_or_used_token_cannot_create_account(self):
        self.assertEqual(
            self.client.get(
                reverse("follower_register", kwargs={"token": "invalid"})
            ).status_code,
            404,
        )
        self.invitation.status = FollowerInvitation.Status.ACCEPTED
        self.invitation.save()
        response = self.client.post(
            reverse("follower_register", kwargs={"token": self.invitation.token}),
            self.follower_data(),
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            get_user_model().objects.filter(email="follower@example.com").exists()
        )

    def test_invitation_email_mismatch_is_rejected(self):
        response = self.client.post(
            reverse("follower_register", kwargs={"token": self.invitation.token}),
            self.follower_data("attacker@example.com"),
        )
        self.assertContains(response, "must match the invitation")
        self.assertFalse(
            get_user_model().objects.filter(email="attacker@example.com").exists()
        )

    def test_blocked_invitation_email_is_rejected(self):
        BlockedDomain.objects.create(domain="example.com")
        response = self.client.post(
            reverse("follower_register", kwargs={"token": self.invitation.token}),
            self.follower_data(),
        )
        self.assertContains(response, "email domain are not accepted")

    def _invite_existing(self, user):
        self.client.force_login(self.member_user)
        return self.client.post(
            reverse("invite_follower"),
            {"name": "Existing Account", "email": user.email},
        )

    def test_existing_follower_and_member_are_approved_without_duplicate_user(self):
        follower = get_user_model().objects.create_user(
            "follower", email="existing-follower@example.com"
        )
        member_user = get_user_model().objects.create_user(
            "W5OTHER", email="existing-member@example.com"
        )
        MemberProfile.objects.create(
            user=member_user,
            callsign="W5OTHER",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        original_count = get_user_model().objects.count()
        self._invite_existing(follower)
        self._invite_existing(member_user)
        self.assertEqual(get_user_model().objects.count(), original_count)
        self.assertEqual(
            FollowRelationship.objects.get(follower=follower).status,
            FollowRelationship.Status.APPROVED,
        )
        self.assertEqual(
            FollowRelationship.objects.get(follower=member_user).status,
            FollowRelationship.Status.APPROVED,
        )

    def test_inactive_user_is_not_auto_approved(self):
        inactive = get_user_model().objects.create_user(
            "inactive", email="inactive@example.com", is_active=False
        )
        self._invite_existing(inactive)
        self.assertFalse(
            FollowRelationship.objects.filter(follower=inactive).exists()
        )

    def test_self_invitation_is_rejected(self):
        self._invite_existing(self.member_user)
        self.assertFalse(
            FollowRelationship.objects.filter(
                member=self.member, follower=self.member_user
            ).exists()
        )


class VerifiedMemberAuthorizationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.follower = User.objects.create_user("follower", password="password")
        self.unverified_user = User.objects.create_user("unverified", password="password")
        MemberProfile.objects.create(
            user=self.unverified_user,
            callsign="W5UNVER",
            callsign_verified=False,
        )
        self.member_user = User.objects.create_user("W5MEMBER", password="password")
        self.member = MemberProfile.objects.create(
            user=self.member_user,
            callsign="W5MEMBER",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.location = Location.objects.create(
            name="Authorization Park", created_by=self.member_user
        )
        self.position = OperatingLocation.objects.create(
            location=self.location, name="Authorization Position"
        )
        self.adventure = Adventure.objects.create(
            owner=self.member_user,
            title="Authorization Adventure",
            location=self.location,
            operating_location=self.position,
        )
        self.entry = JournalEntry.objects.create(
            adventure=self.adventure, body="Authorization journal"
        )
        self.photo = Photo.objects.create(
            journal_entry=self.entry, image="test/auth.jpg"
        )
        self.comment = Comment.objects.create(
            adventure=self.adventure,
            operator=self.member_user,
            body="Authorization comment",
        )

    def member_only_urls(self):
        slug = self.adventure.slug
        return [
            reverse("my_adventures"),
            reverse("add_adventure"),
            reverse("start_adventure_here", args=[self.location.pk]),
            reverse("edit_adventure", args=[slug]),
            reverse("toggle_adventure_visibility", args=[slug]),
            reverse("delete_adventure", args=[slug]),
            reverse("mark_adventure_done", args=[slug]),
            reverse("mark_adventure_in_progress", args=[slug]),
            reverse("add_journal_entry", args=[slug]),
            reverse("edit_journal_entry", args=[self.entry.pk]),
            reverse("toggle_journal_visibility", args=[self.entry.pk]),
            reverse("delete_selected_contacts", args=[self.entry.pk]),
            reverse("import_adif", args=[self.entry.pk]),
            reverse("preview_adif_import", args=[self.entry.pk, "missing"]),
            reverse("confirm_adif_import", args=[self.entry.pk, "missing"]),
            reverse("cancel_adif_import", args=[self.entry.pk, "missing"]),
            reverse("delete_journal_entry", args=[self.entry.pk]),
            reverse("make_cover_photo", args=[self.photo.pk]),
            reverse("delete_photo", args=[self.photo.pk]),
            reverse("add_comment", args=[slug]),
            reverse("delete_comment", args=[self.comment.pk]),
            reverse("create_location"),
            reverse("edit_location", args=[self.location.pk]),
            reverse("add_operating_position", args=[self.location.pk]),
            reverse("edit_operating_position", args=[self.position.pk]),
            reverse("create_operating_position_inline", args=[self.location.pk]),
            reverse("follower_management"),
            reverse("invite_follower"),
            reverse("invitation_action", args=[999999, "cancel"]),
            reverse("respond_to_follow", args=[999999, "approve"]),
            reverse("my_member_profile"),
        ]

    def test_every_member_only_endpoint_uses_shared_boundary(self):
        for url in self.member_only_urls():
            with self.subTest(role="anonymous", url=url):
                self.client.logout()
                self.assertEqual(self.client.get(url).status_code, 302)
            for role, user in [
                ("follower", self.follower),
                ("unverified", self.unverified_user),
            ]:
                with self.subTest(role=role, url=url):
                    self.client.force_login(user)
                    self.assertEqual(self.client.get(url).status_code, 403)
            with self.subTest(role="verified", url=url):
                self.client.force_login(self.member_user)
                self.assertNotEqual(self.client.get(url).status_code, 403)

    def test_follower_cannot_publish_but_verified_member_can(self):
        data = {
            "title": "Boundary Adventure",
            "location": self.location.pk,
            "operating_location": self.position.pk,
        }
        self.client.force_login(self.follower)
        self.assertEqual(
            self.client.post(reverse("add_adventure"), data).status_code, 403
        )
        self.client.force_login(self.member_user)
        self.assertEqual(
            self.client.post(reverse("add_adventure"), data).status_code, 302
        )


class MemberSignupDiscoverabilityTests(TestCase):
    def setUp(self):
        self.member_user = get_user_model().objects.create_user(
            "W5VISIBLE",
            first_name="Rick",
        )
        self.profile = MemberProfile.objects.create(
            user=self.member_user,
            callsign="W5VISIBLE",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )

    def assert_join_link(self, response):
        self.assertContains(
            response,
            f'href="{reverse("register")}"',
        )
        self.assertContains(response, "Join Radio Outdoors")

    def test_signed_out_home_members_and_member_detail_link_to_member_signup(self):
        for url in [
            reverse("home"),
            reverse("members"),
            reverse("member_detail", args=[self.profile.callsign]),
        ]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assert_join_link(response)

    def test_signed_out_header_uses_required_labels(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, ">Sign In<")
        self.assertNotContains(response, ">Create Account<")
        self.assertContains(response, 'class="btn-ro-primary">Sign In')
        self.assertContains(response, 'class="btn-ro-primary home-cta"')
        self.assertContains(response, 'aria-label="Open information menu"')
        self.assertContains(response, "About")
        self.assertContains(response, "Help")
        self.assertContains(response, "Support Radio Outdoors")
        self.assertContains(response, "header-menu.js")
        self.assertContains(response, "Visitor")
        self.assertContains(response, "signed-in-identity")

    def test_adventure_book_link_and_add_action_follow_login_state(self):
        signed_out = self.client.get(reverse("all_adventures"))
        self.assertContains(
            signed_out,
            f'<a href="{reverse("all_adventures")}" class="nav-adventure-book primary-feature-button" aria-current="page">Adventure Book</a>',
        )
        self.assertNotContains(signed_out, ">Add Adventure</a>")

        self.client.force_login(self.member_user)
        public_book = self.client.get(reverse("all_adventures"))
        self.assertContains(
            public_book,
            f'<a href="{reverse("my_adventures")}" class="nav-adventure-book primary-feature-button" aria-current="page">Adventure Book</a>',
        )
        self.assertContains(public_book, ">Add Adventure</a>")

        my_book = self.client.get(reverse("my_adventures"))
        self.assertContains(my_book, ">Add Adventure</a>")

    def test_signed_in_header_uses_accessible_account_menu(self):
        self.client.force_login(self.member_user)
        response = self.client.get(reverse("home"))
        self.assertContains(response, '<details class="account-menu">')
        self.assertContains(response, 'aria-label="Open account menu"')
        self.assertContains(response, "My Account")
        self.assertContains(response, ">Adventure Book</a>")
        self.assertContains(response, ">Locations</a>")
        self.assertContains(response, ">Map</a>")
        from django.conf import settings
        header_source = (settings.BASE_DIR / "templates" / "partials" / "header.html").read_text(encoding="utf-8")
        account_panel = header_source.split('<div class="account-menu-panel">', 1)[1].split("</details>", 1)[0]
        self.assertNotIn(">Adventure Book</a>", account_panel)
        self.assertNotIn(">Locations</a>", account_panel)
        self.assertNotIn(">Map</a>", account_panel)
        self.assertContains(response, "Import POTA History", count=1)
        self.assertContains(response, "Import POTA Contacts", count=1)
        self.assertContains(response, "My Contact Log")
        self.assertNotContains(response, "Admin Tools")
        self.assertContains(response, "About")
        self.assertContains(response, "Help")
        self.assertContains(response, "Support Radio Outdoors")
        self.assertContains(response, "Sign Out")
        self.assertContains(response, 'class="account-menu-separator"', count=2)
        self.assertNotContains(response, ">Create Account<")
        self.assertContains(response, "W5VISIBLE - Rick")
        self.assertContains(response, "signed-in-identity-full")
        self.assertContains(response, "signed-in-identity-compact")

    def test_header_identity_uses_each_members_actual_identity(self):
        second_user = get_user_model().objects.create_user(
            "K0SECOND",
            first_name="Casey",
        )
        MemberProfile.objects.create(
            user=second_user,
            callsign="K0SECOND",
            display_name="Casey Operator",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        expected = [
            (self.member_user, "W5VISIBLE - Rick"),
            (second_user, "K0SECOND - Casey"),
        ]
        for user, identity in expected:
            with self.subTest(identity=identity):
                self.client.force_login(user)
                response = self.client.get(reverse("home"))
                self.assertContains(response, identity)

    def test_member_without_first_name_falls_back_to_callsign(self):
        self.member_user.first_name = ""
        self.member_user.save(update_fields=["first_name"])
        self.client.force_login(self.member_user)
        response = self.client.get(reverse("home"))
        self.assertContains(
            response,
            '<span class="signed-in-identity-full">W5VISIBLE</span>',
        )

    def test_follower_account_menu_hides_member_only_links(self):
        follower = get_user_model().objects.create_user(
            "menu-follower",
            first_name="Alex",
        )
        self.client.force_login(follower)
        response = self.client.get(reverse("home"))
        self.assertContains(response, "My Account")
        self.assertContains(response, "Support Radio Outdoors")
        self.assertNotContains(response, "My Adventures")
        self.assertNotContains(response, "My Followers")
        self.assertContains(response, "Alex - Follower")
        self.assertContains(response, "Alex · Follower")
        self.assertNotContains(response, "QRZ Verified")

    def test_login_page_uses_consistent_primary_action(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, '<h1 id="login-heading">Sign In</h1>')
        self.assertContains(response, 'class="btn-ro-primary login-submit"')

    def test_join_route_is_member_registration_not_follower_registration(self):
        response = self.client.get(reverse("register"))
        self.assertContains(response, "Verified amateur-radio membership")
        self.assertContains(response, 'name="callsign"')
        self.assertNotContains(response, "Create a Follower Account")
        self.assertNotEqual(reverse("register"), reverse(
            "follower_register", kwargs={"token": "invitation-token"}
        ))

    def test_signed_in_users_do_not_see_join_link(self):
        follower = get_user_model().objects.create_user("follower-visible")
        for user in [follower, self.member_user]:
            self.client.force_login(user)
            for url in [reverse("home"), reverse("members")]:
                with self.subTest(user=user.username, url=url):
                    response = self.client.get(url)
                    self.assertNotContains(response, "Join Radio Outdoors")


@override_settings(PHOTO_MODERATION_BACKEND="core.test_photo_moderation.SafeProvider")
class MemberOnboardingAndPhotoTests(TestCase):
    def setUp(self):
        self.media_directory = TemporaryDirectory()
        self.addCleanup(self.media_directory.cleanup)
        media_override = override_settings(MEDIA_ROOT=self.media_directory.name)
        media_override.enable()
        self.addCleanup(media_override.disable)

        self.user = get_user_model().objects.create_user(
            username="W5PHOTO",
            email="photo@example.com",
            password="StrongPass!942",
        )
        self.profile = MemberProfile.objects.create(
            user=self.user,
            callsign="W5PHOTO",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
            qrz_first_name="Photo",
            qrz_last_name="Operator",
        )
        self.client.force_login(self.user)

    def image_upload(self, name, size=(2200, 1600), color="navy"):
        image = Image.new("RGB", size, color)
        output = BytesIO()
        image.save(output, format="PNG")
        return SimpleUploadedFile(
            name,
            output.getvalue(),
            content_type="image/png",
        )

    def profile_data(self, **overrides):
        data = {
            "display_name": "Photo Operator",
            "bio": "Outdoor operator.",
            "home_city": "Austin",
            "home_state": "TX",
            "home_country": "USA",
            "website": "",
            "profile_is_public": "on",
            "email_visible_to_members": "",
            "first_name": "Photo",
            "last_name": "Operator",
            "email": "photo@example.com",
        }
        data.update(overrides)
        return data

    def test_upload_optimizes_and_displays_profile_photo(self):
        response = self.client.post(
            reverse("my_member_profile"),
            self.profile_data(
                profile_photo=self.image_upload("large-photo.png")
            ),
        )
        self.assertRedirects(
            response,
            reverse("member_detail", args=[self.profile.callsign]),
        )
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.profile_photo.name.endswith(".jpg"))
        with self.profile.profile_photo.open("rb") as stored:
            with Image.open(stored) as image:
                self.assertEqual(image.format, "JPEG")
                self.assertLessEqual(max(image.size), 1200)

        self.assertContains(
            self.client.get(reverse("member_detail", args=[self.profile.callsign])),
            self.profile.profile_photo.url,
        )
        self.assertContains(
            self.client.get(reverse("members")),
            self.profile.profile_photo.url,
        )

    def test_replace_and_remove_profile_photo(self):
        self.client.post(
            reverse("my_member_profile"),
            self.profile_data(
                profile_photo=self.image_upload("first.png", color="red")
            ),
        )
        self.profile.refresh_from_db()
        first_name = self.profile.profile_photo.name

        self.client.post(
            reverse("my_member_profile"),
            self.profile_data(
                profile_photo=self.image_upload("second.png", color="green")
            ),
        )
        self.profile.refresh_from_db()
        self.assertNotEqual(self.profile.profile_photo.name, first_name)
        self.assertFalse(self.profile.profile_photo.storage.exists(first_name))

        self.client.post(
            reverse("my_member_profile"),
            self.profile_data(remove_profile_photo="on"),
        )
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.profile_photo)

    def test_existing_member_without_photo_uses_placeholder(self):
        detail = self.client.get(
            reverse("member_detail", args=[self.profile.callsign])
        )
        listing = self.client.get(reverse("members"))
        self.assertContains(detail, "profile picture placeholder")
        self.assertContains(listing, "member-profile-photo-placeholder")

    def test_profile_edit_does_not_offer_or_change_callsign(self):
        response = self.client.get(reverse("my_member_profile"))
        self.assertNotContains(response, 'name="callsign"')
        self.client.post(
            reverse("my_member_profile"),
            self.profile_data(callsign="N0CHANGED"),
        )
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.callsign, "W5PHOTO")

    def test_member_photo_preview_controls_do_not_save_on_page_load(self):
        before_name = self.profile.profile_photo.name
        response = self.client.get(reverse("my_member_profile"))
        self.assertContains(response, "data-photo-preview")
        self.assertContains(response, "Load Photo")
        self.assertContains(response, "Change Photo")
        self.assertContains(response, "Clear Selection")
        self.assertContains(response, "photo-preview.js")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.profile_photo.name, before_name)

    def test_home_ctas_share_component_and_destinations(self):
        self.client.logout()
        response = self.client.get(reverse("home"))
        self.assertContains(response, "home-cta", count=2)
        self.assertContains(response, reverse("all_adventures"))
        self.assertContains(response, reverse("register"))


class MemberManagementVerificationTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_superuser(
            username="admin-verify",
            email="admin@example.com",
            password="StrongPass!942",
        )
        self.ordinary = get_user_model().objects.create_user(
            username="ordinary-user",
            password="StrongPass!942",
        )
        self.member_user = get_user_model().objects.create_user(
            username="W5VERIFY",
            password="StrongPass!942",
        )
        self.profile = MemberProfile.objects.create(
            user=self.member_user,
            callsign="w5verify",
            callsign_verified=False,
            display_name="Member Edited Name",
            home_city="Member Edited City",
            profile_is_public=True,
        )

    def qrz_result(self):
        return QRZResult(
            callsign="W5VERIFY",
            first_name="QRZ First",
            last_name="QRZ Last",
            city="QRZ City",
            state="TX",
            country="United States",
            grid="EM10",
            license_class="General",
            expires="2032-01-01",
        )

    @patch("core.member_views.lookup_callsign")
    def test_staff_can_verify_existing_member_with_shared_qrz_service(self, lookup):
        lookup.return_value = self.qrz_result()
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("member_verify_qrz", args=[self.profile.pk])
        )
        self.assertRedirects(response, reverse("member_admin_list"))
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.callsign_verified)
        self.assertEqual(
            self.profile.verification_method,
            MemberProfile.VerificationMethod.QRZ,
        )
        self.assertIsNotNone(self.profile.verification_at)
        self.assertIsNotNone(self.profile.qrz_verified_at)
        self.assertEqual(self.profile.qrz_first_name, "QRZ First")
        self.assertEqual(self.profile.qrz_grid, "EM10")
        self.assertEqual(self.profile.display_name, "Member Edited Name")
        self.assertEqual(self.profile.home_city, "Member Edited City")
        self.assertEqual(self.profile.verified_by, self.staff)
        lookup.assert_called_once_with("W5VERIFY")

    def assert_qrz_failure_leaves_unverified(self, error, expected_message):
        self.client.force_login(self.staff)
        with patch("core.member_views.lookup_callsign", side_effect=error):
            response = self.client.post(
                reverse("member_verify_qrz", args=[self.profile.pk]),
                follow=True,
            )
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.callsign_verified)
        self.assertContains(response, expected_message)

    def test_qrz_not_found_is_distinguished(self):
        self.assert_qrz_failure_leaves_unverified(
            QRZNotFoundError("not found"),
            "was not found in QRZ",
        )

    def test_qrz_unavailable_is_distinguished(self):
        self.assert_qrz_failure_leaves_unverified(
            QRZUnavailableError("timeout"),
            "temporarily unavailable",
        )

    def test_qrz_configuration_failure_is_distinguished(self):
        self.assert_qrz_failure_leaves_unverified(
            QRZConfigurationError("missing credential file"),
            "credentials or configuration problem",
        )

    def test_ordinary_user_cannot_verify_or_use_development_override(self):
        self.client.force_login(self.ordinary)
        for route in [
            "member_verify_qrz",
            "member_mark_verified_for_development",
            "member_admin_verify",
        ]:
            with self.subTest(route=route):
                response = self.client.post(reverse(route, args=[self.profile.pk]))
                self.assertEqual(response.status_code, 302)
                self.profile.refresh_from_db()
                self.assertFalse(self.profile.callsign_verified)

    @override_settings(DEBUG=True)
    def test_staff_development_override_is_local_only_and_lists_member(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse(
                "member_mark_verified_for_development",
                args=[self.profile.pk],
            ),
            follow=True,
        )
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.callsign_verified)
        self.assertEqual(
            self.profile.verification_method,
            MemberProfile.VerificationMethod.DEVELOPMENT,
        )
        self.assertIsNone(self.profile.qrz_verified_at)
        self.assertEqual(self.profile.verified_by, self.staff)
        self.assertContains(response, "local development only")
        public_listing = self.client.get(reverse("members"))
        self.assertContains(public_listing, "W5VERIFY")
        self.assertTrue(is_verified_member(self.member_user))

    @override_settings(DEBUG=False)
    def test_development_verification_does_not_authorize_in_production(self):
        self.profile.callsign_verified = True
        self.profile.verification_method = (
            MemberProfile.VerificationMethod.DEVELOPMENT
        )
        self.profile.save(
            update_fields=["callsign_verified", "verification_method"]
        )
        self.assertFalse(is_verified_member(self.member_user))
        self.client.force_login(self.member_user)
        response = self.client.get(reverse("add_adventure"))
        self.assertEqual(response.status_code, 403)

    @override_settings(DEBUG=False)
    def test_staff_admin_verification_grants_normal_member_privileges(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("member_admin_verify", args=[self.profile.pk]),
            follow=True,
        )
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.callsign_verified)
        self.assertEqual(
            self.profile.verification_method,
            MemberProfile.VerificationMethod.ADMIN,
        )
        self.assertIsNotNone(self.profile.verification_at)
        self.assertIsNone(self.profile.qrz_verified_at)
        self.assertEqual(self.profile.verified_by, self.staff)
        self.assertContains(response, "Admin Verified")

        self.client.force_login(self.member_user)
        self.assertTrue(is_verified_member(self.member_user))
        self.assertEqual(
            self.client.get(reverse("add_adventure")).status_code,
            200,
        )

    @override_settings(DEBUG=False)
    def test_development_override_is_unavailable_outside_debug(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse(
                "member_mark_verified_for_development",
                args=[self.profile.pk],
            )
        )
        self.assertEqual(response.status_code, 404)
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.callsign_verified)

    def test_management_table_uses_photo_menu_and_clear_status(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("member_admin_list"))
        self.assertContains(response, "member-profile-photo-placeholder")
        self.assertContains(response, "member-admin-menu")
        self.assertContains(response, "Not Verified")
        self.assertContains(response, "View Member")
        self.assertContains(response, "Edit Member")
        self.assertContains(response, "Verify with QRZ")
        self.assertContains(response, "Admin Verify")
        self.assertContains(response, "Deactivate Member")
        self.assertContains(response, "Permanently Delete Account")
        self.assertContains(response, "header-menu.js")
        self.assertContains(response, "ro-data-table")

    def test_activate_deactivate_and_delete_confirmation_work(self):
        self.client.force_login(self.staff)
        toggle_url = reverse("member_toggle_active", args=[self.profile.pk])
        self.assertEqual(self.client.get(toggle_url).status_code, 405)
        self.client.post(toggle_url)
        self.member_user.refresh_from_db()
        self.assertFalse(self.member_user.is_active)
        self.client.post(toggle_url)
        self.member_user.refresh_from_db()
        self.assertTrue(self.member_user.is_active)

        delete_url = reverse("member_delete", args=[self.profile.pk])
        confirmation = self.client.get(delete_url)
        self.assertContains(confirmation, "confirm permanent deletion")
        self.assertContains(confirmation, "DELETE MEMBER")
        self.client.post(delete_url, {"confirmation": "WRONG"})
        self.assertTrue(MemberProfile.objects.filter(pk=self.profile.pk).exists())
        self.client.post(delete_url, {"confirmation": "DELETE MEMBER"})
        self.assertFalse(MemberProfile.objects.filter(pk=self.profile.pk).exists())

    def test_verification_action_is_post_only(self):
        self.client.force_login(self.staff)
        for route in ["member_verify_qrz", "member_admin_verify"]:
            with self.subTest(route=route):
                response = self.client.get(reverse(route, args=[self.profile.pk]))
                self.assertEqual(response.status_code, 405)
