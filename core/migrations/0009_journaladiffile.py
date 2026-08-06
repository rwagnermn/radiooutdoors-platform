from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_location_coordinates"),
    ]

    operations = [
        migrations.CreateModel(
            name="JournalAdifFile",
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
                (
                    "file",
                    models.FileField(upload_to="journal_adif/%Y/%m/"),
                ),
                (
                    "original_name",
                    models.CharField(max_length=255),
                ),
                (
                    "file_size",
                    models.PositiveBigIntegerField(default=0),
                ),
                (
                    "uploaded_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "journal_entry",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="adif_files",
                        to="core.journalentry",
                    ),
                ),
            ],
            options={
                "ordering": ["uploaded_at", "original_name"],
            },
        ),
    ]
