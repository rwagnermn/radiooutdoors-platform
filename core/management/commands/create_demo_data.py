from django.core.management.base import BaseCommand

from core.demo_data import DEMO_PASSWORD, create_demo_data


class Command(BaseCommand):
    help = "Create repeatable development-only Radio Outdoors demo activity."

    def handle(self, *args, **options):
        created = create_demo_data()
        self.stdout.write(self.style.SUCCESS("Development demo data created."))
        self.stdout.write(f"Demo password: {DEMO_PASSWORD}")
        for callsign, adventure_count, journal_count in created:
            self.stdout.write(
                f"{callsign}: {adventure_count} Adventures, "
                f"{journal_count} Journal Entries"
            )
