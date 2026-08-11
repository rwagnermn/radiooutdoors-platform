from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0045_unified_contact_log")]
    operations = [
        migrations.AddField(
            model_name="journalcontact",
            name="signal_report",
            field=models.CharField(blank=True, max_length=20),
        ),
    ]
