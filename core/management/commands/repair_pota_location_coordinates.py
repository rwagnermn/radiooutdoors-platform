from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from adventures.pota_geocoding import entity_region, geocode_pota_park
from adventures.pota_import import clean_pota_park_name
from core.models import Location, PotaActivationImport


class Command(BaseCommand):
    help = "Repair coordinates only for proven POTA-import-created Locations that remain pinless."

    def add_arguments(self, parser):
        parser.add_argument("--location-id", type=int, action="append", dest="location_ids")

    def handle(self, *args, **options):
        queryset = Location.objects.filter(
            description__startswith="Created from POTA historical import.",
        ).filter(Q(latitude__isnull=True) | Q(longitude__isnull=True)).order_by("pk")
        if options["location_ids"]:
            queryset = queryset.filter(pk__in=options["location_ids"])

        repaired = 0
        unresolved = 0
        for location in queryset:
            activation = (
                PotaActivationImport.objects.filter(adventure__location=location)
                .order_by("pk")
                .first()
            )
            if activation is None:
                unresolved += 1
                self.stdout.write(f"Location {location.pk}: unresolved (no POTA activation provenance relationship).")
                continue

            reference = activation.park_reference.strip().upper()
            park_name = clean_pota_park_name(reference, activation.park_name)
            result = geocode_pota_park(reference, park_name, activation.entity, force_refresh=True)
            candidates = result.get("candidates", [])
            if result.get("status") != "found" or len(candidates) != 1:
                unresolved += 1
                category = result.get("failure_category") or result.get("status") or "unknown"
                self.stdout.write(f"Location {location.pk}: unresolved ({category}).")
                continue

            candidate = candidates[0]
            region = entity_region(activation.entity)
            with transaction.atomic():
                locked = Location.objects.select_for_update().get(pk=location.pk)
                if locked.latitude is not None or locked.longitude is not None:
                    continue
                locked.name = f"{park_name} — {reference}"
                locked.reference_code = reference
                locked.state = region["region_code"]
                locked.country = "USA" if region["country_code"] == "US" else region["country_name"]
                locked.latitude = candidate["latitude"]
                locked.longitude = candidate["longitude"]
                locked.description = (
                    "Created from POTA historical import. Coordinate source: POTA park-name geocoding. "
                    "Coordinate quality: approximate/general park location. "
                    f"Provider suggestion: {candidate['provider_name']}."
                )
                locked.save(update_fields=[
                    "name", "reference_code", "state", "country", "latitude", "longitude", "description"
                ])
            repaired += 1
            self.stdout.write(self.style.SUCCESS(f"Location {location.pk}: repaired."))

        self.stdout.write(f"Repaired: {repaired}; unresolved: {unresolved}.")
