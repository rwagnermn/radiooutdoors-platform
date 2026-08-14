from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("core", "0051_journal_location_workflow")]

    operations = [
        migrations.AddField(
            model_name="journalentry",
            name="primary_photo",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="primary_for_journals",
                to="core.photo",
            ),
        ),
    ]
