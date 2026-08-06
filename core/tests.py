from django.test import TestCase

# Create your tests here.


from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from .models import Adventure


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
