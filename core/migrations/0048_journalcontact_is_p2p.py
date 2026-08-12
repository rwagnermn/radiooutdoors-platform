from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0047_journalcontact_resolved_location")]

    operations = [
        migrations.AddField(
            model_name="journalcontact",
            name="is_p2p",
            field=models.BooleanField(default=False),
        ),
    ]
