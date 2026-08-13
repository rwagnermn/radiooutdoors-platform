from django.db import migrations, models
import django.db.models.deletion

def forwards(apps, schema_editor):
    Adventure = apps.get_model("core", "Adventure")
    Journal = apps.get_model("core", "JournalEntry")
    Location = apps.get_model("core", "Location")
    Location.objects.filter(description__startswith="Created from POTA").update(visibility="public")
    Adventure.objects.filter(pota_import__isnull=False).update(is_public=True)
    for adventure in Adventure.objects.filter(journal_entries__isnull=True).select_related("location"):
        Journal.objects.create(
            adventure=adventure,
            location=adventure.location,
            latitude=adventure.location.latitude if adventure.location else None,
            longitude=adventure.location.longitude if adventure.location else None,
            title="Imported Adventure",
            body=adventure.summary or "Imported Adventure record.",
            entry_at=adventure.started_at,
            operating_callsign=adventure.operating_callsign,
            is_public=True,
            status="completed",
        )
    for journal in Journal.objects.select_related("adventure__location").iterator():
        location = journal.adventure.location
        if hasattr(journal.adventure, "pota_import"):
            journal.is_public = True
        journal.status = "completed"
        if location:
            journal.location_id = location.pk
            journal.latitude = location.latitude
            journal.longitude = location.longitude
        journal.save(update_fields=["is_public", "status", "location", "latitude", "longitude"])
    for adventure in Adventure.objects.all().iterator():
        statuses = list(adventure.journal_entries.filter(is_adventure_photo_collection=False).values_list("status", flat=True))
        adventure.status = "completed" if statuses and all(value == "completed" for value in statuses) else "active"
        adventure.completed_at = adventure.updated_at if adventure.status == "completed" else None
        adventure.save(update_fields=["status", "completed_at"])

class Migration(migrations.Migration):
    dependencies = [("core", "0050_location_amenities")]
    operations = [
        migrations.AddField(model_name="journalentry", name="location", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="journal_entries", to="core.location")),
        migrations.AddField(model_name="journalentry", name="latitude", field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
        migrations.AddField(model_name="journalentry", name="longitude", field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
        migrations.AddField(model_name="journalentry", name="status", field=models.CharField(choices=[("open", "Open"), ("completed", "Complete")], default="open", max_length=12)),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
