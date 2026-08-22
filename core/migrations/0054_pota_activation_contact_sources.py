from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0053_group_pota_activations_by_adventure")]

    operations = [
        migrations.AlterField(
            model_name="potaimportbatch",
            name="source",
            field=models.CharField(
                choices=[
                    ("activation_history", "POTA Activation History"),
                    ("hunter_log", "POTA Hunter Log"),
                    ("activation_contacts", "POTA Activation Contacts"),
                ],
                default="activation_history",
                max_length=24,
            ),
        ),
        migrations.AlterField(
            model_name="journalcontact",
            name="source",
            field=models.CharField(
                choices=[
                    ("manual", "Manual"),
                    ("pota_hunter", "POTA Hunter Log"),
                    ("pota_contacts", "POTA Activation Contacts"),
                    ("adif", "ADIF"),
                    ("other", "Other"),
                ],
                db_index=True,
                default="manual",
                max_length=24,
            ),
        ),
        migrations.AlterField(
            model_name="potaactivationimport",
            name="source",
            field=models.CharField(
                choices=[
                    ("activation_history", "POTA Activation History"),
                    ("hunter_log", "POTA Hunter Log"),
                    ("activation_contacts", "POTA Activation Contacts"),
                ],
                default="activation_history",
                max_length=24,
            ),
        ),
    ]
