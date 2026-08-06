from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_location_address_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="location",
            name="latitude",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                max_digits=9,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="location",
            name="longitude",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                max_digits=9,
                null=True,
            ),
        ),
    ]
