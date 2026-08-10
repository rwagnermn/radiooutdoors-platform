from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0041_pota_historical_import"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PotaTestResetAudit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("performed_at", models.DateTimeField(auto_now_add=True)),
                ("database_identifier", models.CharField(max_length=500)),
                ("deleted_counts", models.JSONField(blank=True, default=dict)),
                ("blocked_counts", models.JSONField(blank=True, default=dict)),
                ("backup_path", models.CharField(blank=True, max_length=500)),
                ("succeeded", models.BooleanField(default=False)),
                ("error_category", models.CharField(blank=True, max_length=80)),
                ("staff_user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="pota_test_reset_audits", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-performed_at"]},
        ),
    ]
