from django.contrib.auth import get_user_model
from django.test import TestCase

from core.location_orphans import delete_orphan_locations, orphan_locations
from core.models import Adventure, JournalEntry, Location


class OrphanLocationCleanupTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("orphan-owner")
        self.adventure = Adventure.objects.create(
            owner=self.owner,
            title="Orphan Cleanup Adventure",
            is_public=True,
        )

    def test_only_zero_journal_locations_qualify_and_are_deleted(self):
        orphan = Location.objects.create(name="Unused Location")
        used = Location.objects.create(name="Used Location")
        JournalEntry.objects.create(
            adventure=self.adventure,
            location=used,
            title="Uses Location",
            body="Journal body.",
        )

        self.assertQuerySetEqual(
            orphan_locations().order_by("pk"), [orphan], transform=lambda item: item
        )
        result = delete_orphan_locations()

        self.assertEqual(result.ids, (orphan.pk,))
        self.assertEqual(result.deleted_locations, 1)
        self.assertFalse(Location.objects.filter(pk=orphan.pk).exists())
        self.assertTrue(Location.objects.filter(pk=used.pk).exists())

    def test_location_referenced_by_any_journal_is_never_deleted(self):
        first = Location.objects.create(name="First Shared Location")
        second = Location.objects.create(name="Second Shared Location")
        JournalEntry.objects.create(
            adventure=self.adventure,
            location=first,
            title="First Journal",
            body="First body.",
        )
        JournalEntry.objects.create(
            adventure=self.adventure,
            location=second,
            title="Second Journal",
            body="Second body.",
        )

        result = delete_orphan_locations()

        self.assertEqual(result.deleted_locations, 0)
        self.assertCountEqual(
            Location.objects.values_list("pk", flat=True), [first.pk, second.pk]
        )

    def test_shared_location_usage_count_remains_journal_based(self):
        shared = Location.objects.create(name="Shared Location")
        other_adventure = Adventure.objects.create(
            owner=self.owner,
            title="Other Adventure",
            is_public=True,
        )
        JournalEntry.objects.create(
            adventure=self.adventure,
            location=shared,
            title="Shared One",
            body="First use.",
        )
        JournalEntry.objects.create(
            adventure=other_adventure,
            location=shared,
            title="Shared Two",
            body="Second use.",
        )

        delete_orphan_locations()

        shared.refresh_from_db()
        self.assertEqual(shared.journal_entries.count(), 2)
        self.assertFalse(orphan_locations().filter(pk=shared.pk).exists())
