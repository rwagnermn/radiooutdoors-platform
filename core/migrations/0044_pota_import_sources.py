from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0043_location_needs_pin_review")]

    operations = [
        migrations.AddField(
            model_name="potaimportbatch",
            name="source",
            field=models.CharField(
                choices=[("activation_history", "POTA Activation History"), ("hunter_log", "POTA Hunter Log")],
                default="activation_history",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="potaactivationimport",
            name="source",
            field=models.CharField(
                choices=[("activation_history", "POTA Activation History"), ("hunter_log", "POTA Hunter Log")],
                default="activation_history",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="potaactivationimport",
            name="source_metadata",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
