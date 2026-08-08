from django.core.management.base import BaseCommand

from core.models import DefaultLocationImage, Location, MemberProfile, Photo
from core.photo_moderation import moderate_default_location_image, moderate_location_photo, moderate_photo, moderate_profile_photo


class Command(BaseCommand):
    help = "Submit existing, non-approved uploaded images to the configured moderation provider."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0)

    def handle(self, *args, **options):
        limit = options["limit"]
        scanned = 0
        sources = (
            (Photo.objects.exclude(image="").exclude(moderation_status="approved"), moderate_photo),
            (Location.objects.exclude(photo="").exclude(photo_moderation_status="approved"), moderate_location_photo),
            (MemberProfile.objects.exclude(profile_photo="").exclude(profile_photo_moderation_status="approved"), moderate_profile_photo),
            (DefaultLocationImage.objects.exclude(image="").exclude(moderation_status="approved"), moderate_default_location_image),
        )
        for queryset, scanner in sources:
            for instance in queryset.iterator():
                if limit and scanned >= limit:
                    break
                scanner(instance)
                scanned += 1
            if limit and scanned >= limit:
                break
        self.stdout.write(self.style.SUCCESS(f"Processed {scanned} image(s). Unapproved images remain hidden."))
