from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_journalentry_operating_modes"),
    ]

    operations = [
        migrations.AddField(
            model_name="adventure",
            name="summary",
            field=models.TextField(
                blank=True,
                help_text="A short overview of the whole Adventure.",
            ),
        ),
        migrations.AddField(
            model_name="adventure",
            name="lessons_learned",
            field=models.TextField(
                blank=True,
                help_text="What should you remember for next time?",
            ),
        ),
    ]
