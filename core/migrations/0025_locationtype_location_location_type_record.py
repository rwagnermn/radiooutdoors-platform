from django.db import migrations, models
import django.db.models.deletion
from django.db.models.functions import Lower


EXISTING_TYPES = [
    ("park", "Park"),
    ("campground", "Campground"),
    ("trail", "Trail"),
    ("boat_launch", "Boat Launch"),
    ("scenic_overlook", "Scenic Overlook"),
    ("beach", "Beach"),
    ("cabin", "Cabin"),
    ("backyard", "Backyard"),
    ("summit", "Summit"),
    ("island", "Island"),
    ("rest_area", "Rest Area"),
    ("airport", "Airport"),
    ("wma_dnr", "WMA / DNR Wildlife Management Land"),
    ("other", "Other"),
]


def create_types_and_associate_locations(apps, schema_editor):
    LocationType = apps.get_model("core", "LocationType")
    Location = apps.get_model("core", "Location")
    aliases = {}
    for order, (key, name) in enumerate(EXISTING_TYPES, start=10):
        record, _ = LocationType.objects.get_or_create(
            key=key,
            defaults={"name": name, "is_active": True, "display_order": order},
        )
        aliases[key] = record.pk
    for key, type_id in aliases.items():
        Location.objects.filter(location_type=key).update(location_type_record_id=type_id)


def detach_locations_and_remove_seeded_types(apps, schema_editor):
    Location = apps.get_model("core", "Location")
    LocationType = apps.get_model("core", "LocationType")
    Location.objects.update(location_type_record_id=None)
    LocationType.objects.filter(key__in=[key for key, _ in EXISTING_TYPES]).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0024_alter_location_location_type")]

    operations = [
        migrations.CreateModel(
            name="LocationType",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.SlugField(editable=False, max_length=30, unique=True)),
                ("name", models.CharField(max_length=100)),
                ("is_active", models.BooleanField(default=True)),
                ("display_order", models.PositiveIntegerField(default=0)),
            ],
            options={"ordering": ["display_order", "name"]},
        ),
        migrations.AddConstraint(
            model_name="locationtype",
            constraint=models.UniqueConstraint(Lower("name"), name="core_location_type_name_ci_unique"),
        ),
        migrations.AddField(
            model_name="location",
            name="location_type_record",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="locations",
                to="core.locationtype",
            ),
        ),
        migrations.RunPython(
            create_types_and_associate_locations,
            detach_locations_and_remove_seeded_types,
        ),
    ]
