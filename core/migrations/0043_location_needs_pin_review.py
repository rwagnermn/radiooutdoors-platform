from django.db import migrations, models
from django.db.models import Q


def mark_pinless_imported_locations(apps, schema_editor):
    Location = apps.get_model("core", "Location")
    Location.objects.filter(
        description__startswith="Created from POTA historical import.",
    ).filter(Q(latitude__isnull=True) | Q(longitude__isnull=True)).update(needs_pin_review=True)


class Migration(migrations.Migration):
    dependencies = [("core", "0042_potatestresetaudit")]

    operations = [
        migrations.AddField(
            model_name="location",
            name="needs_pin_review",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text="Imported historical Location is waiting for a general map pin.",
            ),
        ),
        migrations.RunPython(mark_pinless_imported_locations, migrations.RunPython.noop),
    ]
