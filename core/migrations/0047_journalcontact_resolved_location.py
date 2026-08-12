from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("core", "0046_journalcontact_signal_report")]

    operations = [
        migrations.AddField(
            model_name="journalcontact",
            name="resolved_location",
            field=models.ForeignKey(
                blank=True,
                help_text="Approximate park Location resolved for this Contact.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="contacts",
                to="core.location",
            ),
        ),
    ]
