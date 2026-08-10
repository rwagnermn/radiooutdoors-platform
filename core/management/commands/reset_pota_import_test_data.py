from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from core.pota_test_reset import (
    CONFIRMATION_PHRASE,
    PotaResetSafetyError,
    assert_development_database,
    build_reset_preview,
    execute_reset,
)


class Command(BaseCommand):
    help = "Dry-run or safely remove records proven to have been created by POTA test imports."

    def add_arguments(self, parser):
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--no-input", action="store_true", help="Automated isolated-test databases only.")

    def handle(self, *args, **options):
        allow_test_database = bool(options["no_input"])
        try:
            assert_development_database(allow_test_database=allow_test_database)
        except PotaResetSafetyError as exc:
            raise CommandError(str(exc)) from exc
        preview = build_reset_preview()
        self.stdout.write("POTA import test-data reset preview (dry-run)")
        for key, value in preview["counts"].items():
            self.stdout.write(f"  {key}: {value}")
        self.stdout.write(f"  blocked records: {len(preview['blocked'])}")
        self.stdout.write(f"  retained shared/manual Locations: {len(preview['retained_locations'])}")
        for item in preview["blocked"]:
            self.stdout.write(f"  BLOCKED Adventure {item['id']}: {item['reason']}")
        if not options["execute"]:
            self.stdout.write("Dry-run only. No records changed.")
            return
        if options["no_input"]:
            name = str(connection.settings_dict["NAME"])
            if not (name.startswith("file:memorydb_") or "test_" in name):
                raise CommandError("--no-input is permitted only for an isolated automated test database.")
        else:
            entered = input(f'Type "{CONFIRMATION_PHRASE}" to continue: ')
            if entered != CONFIRMATION_PHRASE:
                raise CommandError("Confirmation phrase did not match. Nothing was deleted.")
        try:
            result = execute_reset(allow_test_database=allow_test_database)
        except Exception as exc:
            raise CommandError(f"POTA reset failed safely: {type(exc).__name__}") from exc
        self.stdout.write(self.style.SUCCESS("POTA test-import reset complete."))
        self.stdout.write(f"Backup: {result.backup_path}")
        for key, value in result.deleted.items():
            self.stdout.write(f"  deleted {key}: {value}")
        self.stdout.write(f"Integrity: {result.integrity}")
