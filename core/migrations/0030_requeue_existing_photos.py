from django.db import migrations


def requeue_existing_images(apps, schema_editor):
    Photo = apps.get_model("core", "Photo")
    Photo.objects.exclude(image="").update(
        moderation_status="pending",
        automated_decision="",
        moderation_categories=[],
        moderation_confidence=None,
        moderation_reason="",
        reviewed_by=None,
        reviewed_at=None,
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0029_photo_moderation")]
    operations = [migrations.RunPython(requeue_existing_images, migrations.RunPython.noop)]
