from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0048_journalcontact_is_p2p")]

    operations = [
        migrations.AddField(
            model_name="memberprofile",
            name="mobile_phone",
            field=models.CharField(blank=True, max_length=16),
        ),
        migrations.AddField(
            model_name="memberprofile",
            name="phone_verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
