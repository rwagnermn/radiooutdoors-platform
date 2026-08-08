import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0026_remove_locationtype_display_order"),
    ]

    operations = [
        migrations.AlterField(
            model_name="memberprofile",
            name="verification_method",
            field=models.CharField(
                choices=[
                    ("none", "Not Verified"),
                    ("qrz", "QRZ Verified"),
                    ("manual", "Manual Verification"),
                    ("admin", "Admin Verified"),
                    ("development", "Development Only"),
                ],
                db_index=True,
                default="none",
                max_length=12,
            ),
        ),
        migrations.CreateModel(
            name="ManualVerificationRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("full_name", models.CharField(max_length=160)),
                ("country", models.CharField(max_length=120)),
                ("authority_url", models.URLField(verbose_name="Official licensing authority or recognized callbook link")),
                ("explanation", models.TextField(blank=True)),
                ("status", models.CharField(choices=[("pending", "Pending Review"), ("more_info", "More Information Requested"), ("rejected", "Not Approved"), ("approved", "Approved")], db_index=True, default="pending", max_length=16)),
                ("reviewer_message", models.TextField(blank=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("member", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="manual_verification_request", to="core.memberprofile")),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reviewed_manual_verifications", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["status", "created_at"]},
        ),
    ]
