from django.db import migrations, models


def preserve_old_other_method(apps, schema_editor):
    JournalEntry = apps.get_model("core", "JournalEntry")
    JournalEntry.objects.exclude(other_operating_method="").update(other_method=True)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_alter_location_options_remove_location_latitude_and_more"),
    ]

    operations = [
        migrations.AddField(model_name="journalentry", name="portable", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="journalentry", name="mobile", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="journalentry", name="sota", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="journalentry", name="wwff", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="journalentry", name="contest", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="journalentry", name="field_day", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="journalentry", name="club_event", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="journalentry", name="other_method", field=models.BooleanField(default=False)),
        migrations.RunPython(preserve_old_other_method, migrations.RunPython.noop),
    ]
