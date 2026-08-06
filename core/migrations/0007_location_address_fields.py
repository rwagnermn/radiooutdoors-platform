from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_location_website_reference"),
    ]

    operations = [
        migrations.AddField(
            model_name="location",
            name="street_address",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="location",
            name="address_line_2",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="location",
            name="postal_code",
            field=models.CharField(blank=True, max_length=20),
        ),
    ]
