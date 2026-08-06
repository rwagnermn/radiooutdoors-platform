from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0016_identity_foundation"),
    ]

    operations = [
        migrations.AlterField(
            model_name="location",
            name="location_type",
            field=models.CharField(
                choices=[
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
                    ("wma_dnr", "WMA / DNR Wildlife Management Land"),
                    ("other", "Other"),
                ],
                default="other",
                max_length=30,
            ),
        ),
    ]
