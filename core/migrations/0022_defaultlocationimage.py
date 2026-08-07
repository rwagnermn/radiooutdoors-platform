from django.db import migrations, models


DEFAULTS = [
    ("park", "location_defaults/park.jpg", "Picnic Overlook at Lake Wissota State Park", "https://commons.wikimedia.org/wiki/File:LakeWissotaStatePark1.jpg", "McGhiever", "Public domain", "https://creativecommons.org/publicdomain/mark/1.0/"),
    ("campground", "location_defaults/campground.jpg", "Tent camping at Cleburne State Park", "https://commons.wikimedia.org/wiki/File:CSP_tent_camping.jpg", "Stephen Denny", "Public domain", "https://creativecommons.org/publicdomain/mark/1.0/"),
    ("wildlife", "location_defaults/wildlife.jpg", "Grassland", "https://commons.wikimedia.org/wiki/File:Grassland_.jpg", "Kushal P K", "CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/"),
    ("airport", "location_defaults/airport.jpg", "General aviation hangar and heliport", "https://commons.wikimedia.org/wiki/File:Klagenfurt_Airport_-_Hangar,_General_Aviation,_Heliport.jpg", "Zacke82", "CC BY-SA 3.0", "https://creativecommons.org/licenses/by-sa/3.0/"),
    ("boat_launch", "location_defaults/boat_launch.jpg", "Lacamas Lake boat launch", "https://commons.wikimedia.org/wiki/File:US-WA-lacamas_lake-north_boat_launch-tar.jpg", "Triddle", "Public domain", "https://creativecommons.org/publicdomain/mark/1.0/"),
    ("scenic", "location_defaults/scenic.jpg", "San Bernardino National Forest scenic overlook", "https://commons.wikimedia.org/wiki/File:San_Bernardino_National_Forest_scenic_overlook.jpg", "APK", "CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/"),
]


def seed_defaults(apps, schema_editor):
    DefaultLocationImage = apps.get_model("core", "DefaultLocationImage")
    for key, image, title, source_url, creator, license_name, license_url in DEFAULTS:
        DefaultLocationImage.objects.update_or_create(
            key=key,
            defaults={
                "image": image,
                "source_title": title,
                "source_url": source_url,
                "creator": creator,
                "license_name": license_name,
                "license_url": license_url,
                "displayed_credit": f"{title} by {creator}",
                "active": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("core", "0021_location_photo")]

    operations = [
        migrations.CreateModel(
            name="DefaultLocationImage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(choices=[("park", "Park / General Outdoor Site"), ("campground", "Campground / Cabin"), ("wildlife", "WMA / Wildlife Area"), ("airport", "Airport / Aviation Site"), ("boat_launch", "Boat Launch / Marina"), ("scenic", "Scenic Overlook / Other")], max_length=30, unique=True)),
                ("image", models.ImageField(blank=True, upload_to="location_defaults/")),
                ("source_title", models.CharField(max_length=240)),
                ("source_url", models.URLField()),
                ("creator", models.CharField(max_length=180)),
                ("license_name", models.CharField(max_length=100)),
                ("license_url", models.URLField()),
                ("displayed_credit", models.CharField(blank=True, max_length=320)),
                ("active", models.BooleanField(default=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["key"]},
        ),
        migrations.RunPython(seed_defaults, migrations.RunPython.noop),
    ]
