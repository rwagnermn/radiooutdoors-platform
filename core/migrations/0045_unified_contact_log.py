from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_contact_ownership(apps, schema_editor):
    Contact = apps.get_model("core", "JournalContact")
    for contact in Contact.objects.select_related("journal_entry__adventure").iterator():
        if contact.journal_entry_id:
            contact.owner_id = contact.journal_entry.adventure.owner_id
            contact.source = "adif"
            contact.save(update_fields=["owner_id", "source"])


class Migration(migrations.Migration):
    dependencies = [("core", "0044_pota_import_sources"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AlterField(model_name="journalcontact", name="journal_entry", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="contacts", to="core.journalentry")),
        migrations.AddField(model_name="journalcontact", name="owner", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="contacts", to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name="journalcontact", name="adventure", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="direct_contacts", to="core.adventure")),
        migrations.AddField(model_name="journalcontact", name="station_callsign", field=models.CharField(blank=True, max_length=32)),
        migrations.AddField(model_name="journalcontact", name="operator_callsign", field=models.CharField(blank=True, max_length=32)),
        migrations.AddField(model_name="journalcontact", name="submode", field=models.CharField(blank=True, max_length=32)),
        migrations.AddField(model_name="journalcontact", name="source", field=models.CharField(choices=[("manual", "Manual"), ("pota_hunter", "POTA Hunter Log"), ("adif", "ADIF"), ("other", "Other")], db_index=True, default="manual", max_length=24)),
        migrations.AddField(model_name="journalcontact", name="pota_park_reference", field=models.CharField(blank=True, db_index=True, max_length=30)),
        migrations.AddField(model_name="journalcontact", name="pota_park_name", field=models.CharField(blank=True, max_length=200)),
        migrations.RunPython(backfill_contact_ownership, migrations.RunPython.noop),
    ]
