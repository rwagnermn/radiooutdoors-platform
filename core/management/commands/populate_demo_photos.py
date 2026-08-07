from django.core.management.base import BaseCommand

from core.demo_data import populate_demo_photos


class Command(BaseCommand):
    help = "Copy local images into empty development demo Journal photo slots."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            default=r"C:\Users\Rick Wagner\OneDrive\Images",
            help="Folder searched recursively for JPG, JPEG, PNG, and WebP images.",
        )
        parser.add_argument(
            "--seed",
            type=int,
            help="Optional deterministic random seed for repeatable testing.",
        )

    def handle(self, *args, **options):
        result = populate_demo_photos(options["source"], seed=options["seed"])
        self.stdout.write(self.style.SUCCESS("Development demo photos populated."))
        self.stdout.write(f"Source images available: {result['source_count']}")
        self.stdout.write(f"Journal photos created: {result['journal_photos']}")
        self.stdout.write(f"Adventure covers assigned: {result['adventure_covers']}")
        self.stdout.write(f"Location photos created: {result['location_photos']}")
        self.stdout.write(f"Unreadable source images skipped: {result['skipped_invalid']}")
        self.stdout.write(
            f"Duplicate-content source images skipped: {result['skipped_duplicates']}"
        )
