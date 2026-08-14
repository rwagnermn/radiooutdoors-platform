import io
import json
import tempfile
import zipfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from core.models import Adventure, JournalEntry, Photo


class MissingPhotoMediaRestoreTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.media_root = Path(self.temp.name) / "media"
        self.backup_dir = Path(self.temp.name) / "backups"
        self.media_root.mkdir()
        self.backup_dir.mkdir()
        owner = get_user_model().objects.create_user("recovery-owner")
        adventure = Adventure.objects.create(owner=owner, title="Recovery")
        journal = JournalEntry.objects.create(adventure=adventure, body="Recovery")
        self.photo = Photo.objects.create(
            journal_entry=journal,
            image="adventure_photos/recover.jpg",
            moderation_image="photo_derivatives/moderation/recover.jpg",
            web_image="photo_derivatives/web/recover.jpg",
            thumbnail_image="photo_derivatives/thumbnails/recover.jpg",
            derivative_status="ready",
        )

    def make_archive(self, entries, name="media-20260814-100000.zip"):
        archive = self.backup_dir / name
        with zipfile.ZipFile(archive, "w") as target:
            for path, content in entries.items():
                target.writestr(path, content)
        return archive

    def test_dry_run_then_apply_restores_only_missing_referenced_files(self):
        entries = {
            self.photo.image.name: b"original",
            self.photo.moderation_image.name: b"moderation",
            self.photo.web_image.name: b"web",
            self.photo.thumbnail_image.name: b"thumbnail",
            "unreferenced.jpg": b"do not restore",
        }
        self.make_archive(entries)
        existing = self.media_root / self.photo.thumbnail_image.name
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"active-version")
        with override_settings(MEDIA_ROOT=self.media_root):
            dry_output = io.StringIO()
            call_command("restore_missing_photo_media", backup_dir=self.backup_dir, stdout=dry_output)
            self.assertFalse((self.media_root / self.photo.image.name).exists())
            report = json.loads(dry_output.getvalue())
            self.assertEqual(report["existing_files_overwritten"], 0)
            call_command("restore_missing_photo_media", "--apply", backup_dir=self.backup_dir, stdout=io.StringIO())
        self.assertEqual((self.media_root / self.photo.image.name).read_bytes(), b"original")
        self.assertEqual(existing.read_bytes(), b"active-version")
        self.assertFalse((self.media_root / "unreferenced.jpg").exists())

    def test_unsafe_zip_member_stops_recovery(self):
        self.make_archive({"../escape.jpg": b"unsafe"})
        with override_settings(MEDIA_ROOT=self.media_root):
            with self.assertRaises(CommandError):
                call_command("restore_missing_photo_media", backup_dir=self.backup_dir, stdout=io.StringIO())
        self.assertFalse((Path(self.temp.name) / "escape.jpg").exists())
