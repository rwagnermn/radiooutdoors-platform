import os
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.test import override_settings
from django.test.runner import DiscoverRunner


class IsolatedMediaDiscoverRunner(DiscoverRunner):
    """Run every Django test process with storage outside the project media tree."""

    def setup_test_environment(self, **kwargs):
        self._media_directory = TemporaryDirectory(prefix="radiooutdoors-test-media-")
        test_media_root = Path(self._media_directory.name).resolve()
        project_media_root = (Path(settings.BASE_DIR) / "media").resolve()
        if test_media_root == project_media_root or project_media_root in test_media_root.parents:
            self._media_directory.cleanup()
            raise RuntimeError(
                "Refusing to run tests because the isolated MEDIA_ROOT resolves inside "
                f"the project media directory: {test_media_root}"
            )

        self._test_process_previous = os.environ.get("RADIO_OUTDOORS_TEST_PROCESS")
        os.environ["RADIO_OUTDOORS_TEST_PROCESS"] = "1"
        self._media_override = override_settings(MEDIA_ROOT=test_media_root)
        self._media_override.enable()
        self.log(f"Test MEDIA_ROOT: {test_media_root}", level=1)
        try:
            return super().setup_test_environment(**kwargs)
        except Exception:
            self._restore_media_environment()
            raise

    def teardown_test_environment(self, **kwargs):
        try:
            return super().teardown_test_environment(**kwargs)
        finally:
            self._restore_media_environment()

    def _restore_media_environment(self):
        media_override = getattr(self, "_media_override", None)
        if media_override is not None:
            media_override.disable()
            self._media_override = None
        previous = getattr(self, "_test_process_previous", None)
        if previous is None:
            os.environ.pop("RADIO_OUTDOORS_TEST_PROCESS", None)
        else:
            os.environ["RADIO_OUTDOORS_TEST_PROCESS"] = previous
        media_directory = getattr(self, "_media_directory", None)
        if media_directory is not None:
            media_directory.cleanup()
            self._media_directory = None
