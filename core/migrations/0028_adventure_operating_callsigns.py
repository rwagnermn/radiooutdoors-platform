from django.db import migrations, models


def populate_operating_callsigns(apps, schema_editor):
    Adventure = apps.get_model("core", "Adventure")
    JournalEntry = apps.get_model("core", "JournalEntry")
    for adventure in Adventure.objects.select_related("owner", "owner__member_profile"):
        profile = getattr(adventure.owner, "member_profile", None)
        callsign = (
            profile.callsign if profile and profile.callsign else adventure.owner.username
        ).strip().upper()
        Adventure.objects.filter(pk=adventure.pk).update(operating_callsign=callsign)
        JournalEntry.objects.filter(adventure_id=adventure.pk).update(
            operating_callsign=callsign
        )


class Migration(migrations.Migration):
    dependencies = [("core", "0027_manualverificationrequest")]

    operations = [
        migrations.AddField(model_name="adventure", name="operating_callsign", field=models.CharField(blank=True, max_length=30)),
        migrations.AddField(model_name="adventure", name="operating_callsign_type", field=models.CharField(choices=[("personal", "Personal callsign"), ("special_event", "Special Event callsign"), ("club", "Club callsign"), ("contest", "Contest callsign"), ("portable_regional", "Portable/Regional variation"), ("other", "Other authorized callsign")], default="personal", max_length=24)),
        migrations.AddField(model_name="adventure", name="operating_identity_name", field=models.CharField(blank=True, max_length=180, verbose_name="Event or organization name")),
        migrations.AddField(model_name="adventure", name="operating_callsign_explanation", field=models.TextField(blank=True, verbose_name="Optional explanation")),
        migrations.AddField(model_name="adventure", name="operating_callsign_url", field=models.URLField(blank=True, verbose_name="Optional event website/reference")),
        migrations.AddField(model_name="adventure", name="operating_start_date", field=models.DateField(blank=True, null=True, verbose_name="Start date")),
        migrations.AddField(model_name="adventure", name="operating_end_date", field=models.DateField(blank=True, null=True, verbose_name="End date")),
        migrations.AddField(model_name="journalentry", name="operating_callsign", field=models.CharField(blank=True, max_length=30)),
        migrations.RunPython(populate_operating_callsigns, migrations.RunPython.noop),
    ]
