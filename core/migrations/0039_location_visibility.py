from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0038_adventure_cover_selection")]

    operations = [
        migrations.AddField(
            model_name="location",
            name="visibility",
            field=models.CharField(
                choices=[("public", "Public"), ("private", "Private")],
                db_index=True,
                default="public",
                max_length=10,
            ),
        ),
    ]
