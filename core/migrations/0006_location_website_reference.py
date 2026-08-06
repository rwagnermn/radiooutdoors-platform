from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_adventure_summary_lessons_learned"),
    ]

    operations = [
        migrations.AddField(
            model_name="location",
            name="official_website",
            field=models.URLField(
                blank=True,
                help_text=(
                    "Official park, campground, government, "
                    "or location website."
                ),
            ),
        ),
        migrations.AddField(
            model_name="location",
            name="reference_code",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Optional POTA, WWFF, park, airport, "
                    "or other reference."
                ),
                max_length=100,
            ),
        ),
    ]
