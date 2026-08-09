from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0039_location_visibility")]

    operations = [
        migrations.AddField(
            model_name="journalcontact",
            name="band",
            field=models.CharField(blank=True, max_length=24),
        ),
        migrations.AddField(
            model_name="journalcontact",
            name="frequency",
            field=models.DecimalField(
                blank=True, decimal_places=6, max_digits=12, null=True
            ),
        ),
        migrations.AddField(
            model_name="journalcontact",
            name="latitude",
            field=models.DecimalField(
                blank=True, decimal_places=6, max_digits=9, null=True
            ),
        ),
        migrations.AddField(
            model_name="journalcontact",
            name="longitude",
            field=models.DecimalField(
                blank=True, decimal_places=6, max_digits=9, null=True
            ),
        ),
    ]
