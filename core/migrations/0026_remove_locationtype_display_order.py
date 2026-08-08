from django.db import migrations
from django.db.models.functions import Lower


class Migration(migrations.Migration):
    dependencies = [("core", "0025_locationtype_location_location_type_record")]

    operations = [
        migrations.AlterModelOptions(
            name="locationtype",
            options={"ordering": [Lower("name")]},
        ),
        migrations.RemoveField(
            model_name="locationtype",
            name="display_order",
        ),
    ]
