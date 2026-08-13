from django.db import migrations, models


def copy_existing_amenities(apps, schema_editor):
    Location = apps.get_model("core", "Location")
    OperatingLocation = apps.get_model("core", "OperatingLocation")
    fields = ["parking", "restrooms", "picnic_tables", "shelter", "shade", "power", "drinking_water", "cell_coverage_bars", "ambient_noise_level"]
    for location in Location.objects.all().iterator():
        source = OperatingLocation.objects.filter(location_id=location.pk).order_by("created_at", "pk").first()
        if source:
            for field in fields:
                setattr(location, field, getattr(source, field))
            location.save(update_fields=fields)


class Migration(migrations.Migration):
    dependencies = [("core", "0049_memberprofile_mobile_phone")]
    operations = [
        migrations.AddField(model_name="location", name="parking", field=models.CharField(choices=[("unknown", "Unknown"), ("yes", "Yes"), ("no", "No")], default="unknown", max_length=10)),
        migrations.AddField(model_name="location", name="restrooms", field=models.CharField(choices=[("unknown", "Unknown"), ("yes", "Yes"), ("no", "No")], default="unknown", max_length=10)),
        migrations.AddField(model_name="location", name="picnic_tables", field=models.CharField(choices=[("unknown", "Unknown"), ("yes", "Yes"), ("no", "No")], default="unknown", max_length=10)),
        migrations.AddField(model_name="location", name="shelter", field=models.CharField(choices=[("unknown", "Unknown"), ("yes", "Yes"), ("no", "No")], default="unknown", max_length=10)),
        migrations.AddField(model_name="location", name="shade", field=models.CharField(choices=[("unknown", "Unknown"), ("yes", "Yes"), ("no", "No")], default="unknown", max_length=10)),
        migrations.AddField(model_name="location", name="power", field=models.CharField(choices=[("unknown", "Unknown"), ("yes", "Yes"), ("no", "No")], default="unknown", max_length=10)),
        migrations.AddField(model_name="location", name="drinking_water", field=models.CharField(choices=[("unknown", "Unknown"), ("yes", "Yes"), ("no", "No")], default="unknown", max_length=10)),
        migrations.AddField(model_name="location", name="cell_coverage_bars", field=models.PositiveSmallIntegerField(choices=[(0, "Unknown"), (1, "1 Bar"), (2, "2 Bars"), (3, "3 Bars"), (4, "4 Bars"), (5, "5 Bars")], default=0)),
        migrations.AddField(model_name="location", name="ambient_noise_level", field=models.CharField(choices=[("unknown", "Unknown"), ("very_quiet", "Very Quiet"), ("quiet", "Quiet"), ("moderate", "Moderate"), ("busy", "Busy"), ("very_busy", "Very Busy")], default="unknown", max_length=20)),
        migrations.RunPython(copy_existing_amenities, migrations.RunPython.noop),
    ]