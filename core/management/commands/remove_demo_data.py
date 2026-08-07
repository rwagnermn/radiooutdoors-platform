from django.core.management.base import BaseCommand

from core.demo_data import remove_demo_data


class Command(BaseCommand):
    help = "Remove only marker-owned development demo records."

    def handle(self, *args, **options):
        deleted_users, deleted_locations = remove_demo_data()
        self.stdout.write(
            self.style.SUCCESS(
                f"Removed {deleted_users} demo users and "
                f"{deleted_locations} unused demo Location records."
            )
        )
