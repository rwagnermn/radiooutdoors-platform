from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from PIL import Image

from core.demo_data import populate_demo_photos
from core.models import Adventure, JournalEntry, Location, Photo


class PopulateDemoPhotosTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="demo_photos")
        self.adventure = Adventure.objects.create(owner=self.user, title="Photo demo")
        self.entry = JournalEntry.objects.create(
            adventure=self.adventure,
            title="Missing photo",
            body="Development Journal.",
        )

    def make_source(self, directory, name="source.png", size=(2400, 1200)):
        path = Path(directory, name)
        Image.new("RGB", size, "orange").save(path)
        return path

    @override_settings(DEBUG=True)
    def test_populates_only_missing_demo_photos_and_assigns_cover(self):
        with TemporaryDirectory() as source, TemporaryDirectory() as media:
            source_path = self.make_source(source)
            original_bytes = source_path.read_bytes()
            with override_settings(MEDIA_ROOT=media):
                result = populate_demo_photos(source, seed=7)
                self.entry.refresh_from_db()
                self.adventure.refresh_from_db()
                photo = self.entry.photos.get()
                self.assertTrue(Path(photo.image.path).is_file())
                with Image.open(photo.image.path) as image:
                    self.assertLessEqual(max(image.size), 1600)
                self.assertEqual(self.adventure.cover_photo_id, photo.pk)
                self.assertEqual(result["journal_photos"], 1)
                self.assertEqual(result["adventure_covers"], 1)
            self.assertEqual(source_path.read_bytes(), original_bytes)

    @override_settings(DEBUG=True)
    def test_existing_photo_and_non_demo_records_are_preserved(self):
        ordinary_user = get_user_model().objects.create_user(username="ordinary")
        ordinary_adventure = Adventure.objects.create(
            owner=ordinary_user, title="Ordinary record"
        )
        ordinary_entry = JournalEntry.objects.create(
            adventure=ordinary_adventure, body="No demo photo allowed."
        )
        with TemporaryDirectory() as source, TemporaryDirectory() as media:
            self.make_source(source)
            with override_settings(MEDIA_ROOT=media):
                existing = Photo.objects.create(
                    journal_entry=self.entry,
                    image="adventure_photos/existing.jpg",
                )
                result = populate_demo_photos(source, seed=3)
                self.assertEqual(list(self.entry.photos.all()), [existing])
                self.assertFalse(ordinary_entry.photos.exists())
                self.assertEqual(result["journal_photos"], 0)

    @override_settings(DEBUG=True)
    def test_missing_source_fails_safely(self):
        with self.assertRaises(CommandError):
            populate_demo_photos("Z:/definitely-not-a-real-image-folder")

    @override_settings(DEBUG=True)
    def test_duplicate_source_content_is_not_assigned_twice(self):
        second_entry = JournalEntry.objects.create(
            adventure=self.adventure, body="Second missing photo."
        )
        with TemporaryDirectory() as source, TemporaryDirectory() as media:
            first = self.make_source(source, "first.png")
            Path(source, "duplicate.png").write_bytes(first.read_bytes())
            self.make_source(source, "different.png", size=(600, 900))
            with override_settings(MEDIA_ROOT=media):
                result = populate_demo_photos(source, seed=2)
                hashes = set(
                    Photo.objects.filter(
                        journal_entry__in=[self.entry, second_entry]
                    ).values_list("file_hash", flat=True)
                )
                self.assertEqual(len(hashes), 2)
                self.assertEqual(result["skipped_duplicates"], 1)

    @override_settings(DEBUG=True)
    def test_populates_missing_development_location_photo(self):
        location = Location.objects.create(name="Demo — Photo Location")
        with TemporaryDirectory() as source, TemporaryDirectory() as media:
            self.make_source(source, "journal.png")
            self.make_source(source, "location.png", size=(900, 600))
            with override_settings(MEDIA_ROOT=media):
                result = populate_demo_photos(source, seed=4)
                location.refresh_from_db()
                self.assertTrue(location.photo)
                self.assertTrue(Path(location.photo.path).is_file())
                self.assertEqual(result["location_photos"], 1)
                second_result = populate_demo_photos(source, seed=4)
                self.assertEqual(second_result["location_photos"], 0)

    @override_settings(DEBUG=False)
    def test_command_refuses_outside_debug(self):
        with self.assertRaises(CommandError):
            call_command("populate_demo_photos")
