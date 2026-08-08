from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0028_adventure_operating_callsigns"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="photo", name="moderation_status",
            field=models.CharField(choices=[("pending", "Pending Scan"), ("approved", "Approved"), ("review", "Needs Administrator Review"), ("rejected", "Rejected")], default="pending", max_length=12),
        ),
        migrations.AddField(model_name="photo", name="automated_decision", field=models.CharField(blank=True, max_length=32)),
        migrations.AddField(model_name="photo", name="moderation_categories", field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name="photo", name="moderation_confidence", field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name="photo", name="moderation_reason", field=models.CharField(blank=True, max_length=240)),
        migrations.AddField(model_name="photo", name="reviewed_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="photo", name="reviewed_by", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reviewed_photos", to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name="location", name="photo_moderation_status", field=models.CharField(choices=[("pending", "Pending Scan"), ("approved", "Approved"), ("review", "Needs Administrator Review"), ("rejected", "Rejected")], db_index=True, default="pending", max_length=12)),
        migrations.AddField(model_name="location", name="photo_moderation_reason", field=models.CharField(blank=True, max_length=240)),
        migrations.AddField(model_name="location", name="photo_moderation_categories", field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name="location", name="photo_moderation_confidence", field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name="location", name="photo_reviewed_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="location", name="photo_reviewed_by", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reviewed_location_photos", to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name="memberprofile", name="profile_photo_moderation_status", field=models.CharField(choices=[("pending", "Pending Scan"), ("approved", "Approved"), ("review", "Needs Administrator Review"), ("rejected", "Rejected")], db_index=True, default="pending", max_length=12)),
        migrations.AddField(model_name="memberprofile", name="profile_photo_moderation_reason", field=models.CharField(blank=True, max_length=240)),
        migrations.AddField(model_name="memberprofile", name="profile_photo_moderation_categories", field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name="memberprofile", name="profile_photo_moderation_confidence", field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name="memberprofile", name="profile_photo_reviewed_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="memberprofile", name="profile_photo_reviewed_by", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reviewed_profile_photos", to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name="defaultlocationimage", name="moderation_status", field=models.CharField(choices=[("pending", "Pending Scan"), ("approved", "Approved"), ("review", "Needs Administrator Review"), ("rejected", "Rejected")], db_index=True, default="pending", max_length=12)),
        migrations.AddField(model_name="defaultlocationimage", name="moderation_reason", field=models.CharField(blank=True, max_length=240)),
        migrations.AddField(model_name="defaultlocationimage", name="moderation_categories", field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name="defaultlocationimage", name="moderation_confidence", field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name="defaultlocationimage", name="reviewed_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="defaultlocationimage", name="reviewed_by", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reviewed_default_location_images", to=settings.AUTH_USER_MODEL)),
    ]
