from django.test import TestCase

# Create your tests here.


from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from .models import Adventure, Location


class AdventureDisplayStatusTests(TestCase):
    def setUp(self):
        self.operator = get_user_model().objects.create_user(
            username="W5TEST",
            password="test-password",
        )

    def test_recent_active_adventure_is_currently_operating(self):
        adventure = Adventure.objects.create(
            owner=self.operator,
            title="Recent Adventure",
        )
        self.assertEqual(adventure.display_status_key, "operating")
        self.assertEqual(adventure.display_status_label, "Currently Operating")

    def test_old_active_adventure_is_in_progress(self):
        adventure = Adventure.objects.create(
            owner=self.operator,
            title="Older Adventure",
        )
        Adventure.objects.filter(pk=adventure.pk).update(
            updated_at=timezone.now() - timedelta(hours=25)
        )
        adventure.refresh_from_db()

        self.assertEqual(adventure.display_status_key, "progress")
        self.assertEqual(adventure.display_status_label, "In Progress")

    def test_completed_adventure_is_complete(self):
        adventure = Adventure.objects.create(
            owner=self.operator,
            title="Completed Adventure",
            status=Adventure.Status.COMPLETED,
        )
        self.assertEqual(adventure.display_status_key, "complete")
        self.assertEqual(adventure.display_status_label, "Adventure Complete")


class MapExplorerCurrentAdventureTests(TestCase):
    def test_current_adventure_without_operating_position_gets_yellow_location_pin(self):
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
        self.assertEqual(point["kind"], "location")
        self.assertTrue(point["currently_operating"])
        self.assertIsNone(point["operating_location_id"])


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
