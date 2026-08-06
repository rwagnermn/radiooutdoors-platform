from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0010_journalcontact")]
    operations = [
        migrations.AddField(model_name="adventure", name="is_public", field=models.BooleanField(default=True, help_text="Visible to everyone. Turn this off to keep the Adventure private.")),
        migrations.AddField(model_name="journalentry", name="is_public", field=models.BooleanField(default=True, help_text="Visible to everyone who can view this Adventure.")),
    ]
