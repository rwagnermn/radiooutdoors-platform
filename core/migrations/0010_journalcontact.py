from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_journaladiffile"),
    ]

    operations = [
        migrations.DeleteModel(
            name="JournalAdifFile",
        ),
        migrations.CreateModel(
            name="JournalContact",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("qso_date", models.DateField()),
                ("time_on", models.TimeField(blank=True, null=True)),
                ("callsign", models.CharField(max_length=32)),
                ("mode", models.CharField(blank=True, max_length=32)),
                ("name", models.CharField(blank=True, max_length=120)),
                ("state", models.CharField(blank=True, max_length=80)),
                ("country", models.CharField(blank=True, max_length=120)),
                (
                    "distance_miles",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                ("comment", models.TextField(blank=True)),
                ("grid_square", models.CharField(blank=True, max_length=12)),
                (
                    "fingerprint",
                    models.CharField(db_index=True, max_length=64),
                ),
                ("imported_at", models.DateTimeField(auto_now_add=True)),
                (
                    "journal_entry",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="contacts",
                        to="core.journalentry",
                    ),
                ),
            ],
            options={
                "ordering": ["qso_date", "time_on", "callsign"],
            },
        ),
        migrations.AddConstraint(
            model_name="journalcontact",
            constraint=models.UniqueConstraint(
                fields=("journal_entry", "fingerprint"),
                name="unique_contact_per_journal_import",
            ),
        ),
    ]
