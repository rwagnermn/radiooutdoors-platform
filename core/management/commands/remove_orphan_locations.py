from django.core.management.base import BaseCommand

from core.location_orphans import delete_orphan_locations, orphan_locations


class Command(BaseCommand):
    help = "List or transactionally delete Locations unused by every Journal."

    def add_arguments(self, parser):
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Permanently delete the listed zero-Journal Locations.",
        )

    def handle(self, *args, **options):
        candidates = list(orphan_locations().order_by("pk"))
        self.stdout.write(f"Zero-Journal Locations: {len(candidates)}")
        for location in candidates:
            self.stdout.write(
                f"{location.pk}\t{location.name}\t"
                f"{location.latitude}\t{location.longitude}"
            )
        if not options["execute"]:
            self.stdout.write("Dry run only; no records deleted.")
            return

        result = delete_orphan_locations()
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {result.deleted_locations} zero-Journal Locations "
                f"and {result.deleted_related_operating_locations} unused related "
                "operating positions."
            )
        )
