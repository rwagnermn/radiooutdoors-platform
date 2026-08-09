from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def classify_existing_covers(apps, schema_editor):
    Adventure = apps.get_model("core", "Adventure")
    JournalEntry = apps.get_model("core", "JournalEntry")
    JournalEntry.objects.filter(
        title="Adventure photos", body="Photos from this Adventure."
    ).update(is_adventure_photo_collection=True)
    # Existing stored covers may have been deliberately selected. Preserve them.
    Adventure.objects.exclude(cover_photo_id=None).update(cover_photo_is_explicit=True)


class Migration(migrations.Migration):
    dependencies = [("core", "0037_policyacceptance")]

    operations = [
        migrations.AddField(
            model_name="adventure",
            name="cover_photo_is_explicit",
            field=models.BooleanField(default=False, help_text="True when an authorized manager explicitly selected the cover."),
        ),
        migrations.AddField(
            model_name="journalentry",
            name="is_adventure_photo_collection",
            field=models.BooleanField(default=False, help_text="System collection for photos uploaded directly with an Adventure."),
        ),
        migrations.CreateModel(
            name="AdventureCoverSelectionAudit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(default="selected", max_length=32)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ("adventure", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="cover_selection_history", to="core.adventure")),
                ("photo", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to="core.photo")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.RunPython(classify_existing_covers, migrations.RunPython.noop),
    ]
