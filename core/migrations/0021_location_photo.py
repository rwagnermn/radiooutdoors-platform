from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0020_member_verification_method"),
    ]

    operations = [
        migrations.AddField(
            model_name="location",
            name="photo",
            field=models.ImageField(
                blank=True,
                upload_to="location_photos/%Y/%m/",
            ),
        ),
    ]
