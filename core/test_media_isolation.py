import os
from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage
from django.test import SimpleTestCase


class GlobalTestMediaIsolationTests(SimpleTestCase):
    def test_runner_uses_external_temporary_media_root(self):
        project_media_root = (Path(settings.BASE_DIR) / "media").resolve()
        test_media_root = Path(settings.MEDIA_ROOT).resolve()

        self.assertEqual(os.environ.get("RADIO_OUTDOORS_TEST_PROCESS"), "1")
        self.assertNotEqual(test_media_root, project_media_root)
        self.assertNotIn(project_media_root, test_media_root.parents)
        self.assertTrue(test_media_root.name.startswith("radiooutdoors-test-media-"))

    def test_default_storage_resolves_inside_isolated_media_root(self):
        test_media_root = Path(settings.MEDIA_ROOT).resolve()
        storage_root = Path(default_storage.path(".")).resolve()

        self.assertEqual(storage_root, test_media_root)
