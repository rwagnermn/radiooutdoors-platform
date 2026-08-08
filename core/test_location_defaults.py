import json
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from core.location_default_images import (
    commons_image_information,
    default_image_key,
    default_image_storage_name,
    reusable_license,
)
from core.models import DefaultLocationImage, Location


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, *args):
        return self.payload


class LocationDefaultImageTests(TestCase):
    def test_type_and_name_mapping(self):
        self.assertEqual(
            default_image_key(
                Location(name="County Campground", location_type=Location.LocationType.OTHER)
            ),
            "campground",
        )
        self.assertEqual(
            default_image_key(
                Location(name="Municipal Airport", location_type=Location.LocationType.OTHER)
            ),
            "airport",
        )
        self.assertEqual(
            default_image_key(
                Location(name="Wildlife Area", location_type=Location.LocationType.WMA_DNR)
            ),
            "wildlife",
        )
        self.assertEqual(
            default_image_key(
                Location(name="Public Ramp", location_type=Location.LocationType.BOAT_LAUNCH)
            ),
            "boat_launch",
        )
        self.assertEqual(
            default_image_key(
                Location(name="Legacy County Park", location_type=Location.LocationType.OTHER)
            ),
            "park",
        )

    def test_license_allowlist_rejects_unclear_or_restricted_licenses(self):
        self.assertTrue(reusable_license("Public domain"))
        self.assertTrue(reusable_license("CC BY-SA 4.0"))
        self.assertFalse(reusable_license("All rights reserved"))
        self.assertFalse(reusable_license(""))

    @patch("core.location_default_images.urlopen")
    def test_commons_metadata_with_unclear_license_is_rejected(self, mocked_open):
        payload = {
            "query": {
                "pages": {
                    "1": {
                        "imageinfo": [{
                            "url": "https://example.test/image.jpg",
                            "extmetadata": {
                                "LicenseShortName": {"value": "All rights reserved"}
                            },
                        }]
                    }
                }
            }
        }
        mocked_open.return_value = _Response(json.dumps(payload).encode())
        with self.assertRaises(CommandError):
            commons_image_information("File:Restricted.jpg")

    def test_member_photo_wins_then_default_then_placeholder(self):
        with TemporaryDirectory() as media:
            with override_settings(MEDIA_ROOT=media):
                default_storage.save(
                    default_image_storage_name("park"),
                    ContentFile(b"default", name="park.jpg"),
                )
                DefaultLocationImage.objects.filter(key="park").update(
                    moderation_status="approved"
                )
                location = Location.objects.create(
                    name="Fallback Park",
                    location_type=Location.LocationType.PARK,
                )
                self.assertTrue(location.uses_default_photo)
                self.assertIn("location_defaults/park.jpg", location.display_photo_url)
                response = self.client.get(
                    reverse("location_detail", kwargs={"location_id": location.pk})
                )
                self.assertContains(response, "Representative default photo")
                self.assertContains(response, "Public domain")

                location.photo = "location_photos/member.jpg"
                location.photo_moderation_status = "approved"
                location.save(update_fields=["photo", "photo_moderation_status"])
                location.__dict__.pop("default_photo_info", None)
                self.assertFalse(location.uses_default_photo)
                self.assertIn("location_photos/member.jpg", location.display_photo_url)

                default_storage.delete(default_image_storage_name("park"))
                location.photo = ""
                location.save(update_fields=["photo"])
                location.__dict__.pop("default_photo_info", None)
                self.assertEqual(location.display_photo_url, "")
