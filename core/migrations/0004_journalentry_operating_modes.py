from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_journalentry_operating_methods"),
    ]

    operations = [
        migrations.AddField(
            model_name="journalentry",
            name="mode_am",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="journalentry",
            name="mode_cw",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="journalentry",
            name="mode_digital",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="journalentry",
            name="mode_fm",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="journalentry",
            name="mode_other",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="journalentry",
            name="mode_ssb",
            field=models.BooleanField(default=False),
        ),
    ]
