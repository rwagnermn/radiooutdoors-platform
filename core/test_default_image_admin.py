from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from core.models import DefaultLocationImage, Location


class DefaultLocationImageAdminTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(
            username="default-admin",
            password="test-password",
            is_staff=True,
        )
        self.member = User.objects.create_user(
            username="ordinary-member",
            password="test-password",
        )
        self.follower = User.objects.create_user(
            username="ordinary-follower",
            password="test-password",
        )
        self.default_image = DefaultLocationImage.objects.get(key="park")

    def image_upload(self):
        output = BytesIO()
        Image.new("RGB", (2100, 1050), "blue").save(output, format="PNG")
        return SimpleUploadedFile(
            "replacement.png", output.getvalue(), "image/png"
        )

    def test_staff_menu_and_management_table_are_visible(self):
        self.client.force_login(self.staff)
        home = self.client.get(reverse("home"))
        self.assertContains(home, "Default Location Images")
        self.assertContains(home, reverse("default_location_image_list"))

        response = self.client.get(reverse("default_location_image_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Photo Credit / Source")
        self.assertContains(response, "Park / General Outdoor Site")
        self.assertContains(response, "Replace Image")
        self.assertContains(response, "Edit Attribution")
        self.assertContains(response, "Disable")
        self.assertContains(response, "member-admin-menu")
        self.assertContains(response, "ro-data-table")

    def test_management_routes_are_staff_only(self):
        urls = [
            reverse("default_location_image_list"),
            reverse("default_location_image_detail", args=[self.default_image.pk]),
            reverse("default_location_image_edit", args=[self.default_image.pk]),
            reverse("default_location_image_toggle", args=[self.default_image.pk]),
        ]
        for user in [None, self.member, self.follower]:
            if user:
                self.client.force_login(user)
            else:
                self.client.logout()
            for url in urls:
                with self.subTest(user=user, url=url):
                    response = self.client.post(url) if url.endswith("toggle/") else self.client.get(url)
                    self.assertEqual(response.status_code, 302)
            self.assertNotContains(self.client.get(reverse("home")), "Default Location Images")

    def test_attribution_edit_and_enable_disable(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("default_location_image_edit", args=[self.default_image.pk]),
            {
                "source_title": "Edited Park Source",
                "source_url": "https://commons.wikimedia.org/wiki/File:LakeWissotaStatePark1.jpg",
                "creator": "Edited Photographer",
                "license_name": "Public domain",
                "license_url": "https://creativecommons.org/publicdomain/mark/1.0/",
                "displayed_credit": "Custom visible photo credit",
                "active": "on",
            },
        )
        self.assertRedirects(
            response,
            reverse("default_location_image_detail", args=[self.default_image.pk]),
        )
        self.default_image.refresh_from_db()
        self.assertEqual(self.default_image.displayed_credit, "Custom visible photo credit")
        detail = self.client.get(
            reverse("default_location_image_detail", args=[self.default_image.pk])
        )
        self.assertContains(detail, "Custom visible photo credit")

        toggle = reverse("default_location_image_toggle", args=[self.default_image.pk])
        self.assertEqual(self.client.get(toggle).status_code, 405)
        self.client.post(toggle)
        self.default_image.refresh_from_db()
        self.assertFalse(self.default_image.active)
        self.client.post(toggle)
        self.default_image.refresh_from_db()
        self.assertTrue(self.default_image.active)

    def test_replace_image_preview_controls_and_member_photo_priority(self):
        self.client.force_login(self.staff)
        edit_page = self.client.get(
            reverse("default_location_image_edit", args=[self.default_image.pk])
        )
        self.assertContains(edit_page, "data-photo-preview")
        self.assertContains(edit_page, "Load Photo")
        self.assertContains(edit_page, "Nothing is saved until Save Default Image")

        with TemporaryDirectory() as media:
            with override_settings(MEDIA_ROOT=media):
                response = self.client.post(
                    reverse("default_location_image_edit", args=[self.default_image.pk]),
                    {
                        "image": self.image_upload(),
                        "source_title": self.default_image.source_title,
                        "source_url": self.default_image.source_url,
                        "creator": self.default_image.creator,
                        "license_name": self.default_image.license_name,
                        "license_url": self.default_image.license_url,
                        "displayed_credit": self.default_image.displayed_credit,
                        "active": "on",
                    },
                )
                self.assertEqual(response.status_code, 302)
                self.default_image.refresh_from_db()
                with Image.open(self.default_image.image.path) as stored:
                    self.assertLessEqual(max(stored.size), 1600)

        location = Location.objects.create(
            name="Member Photo Priority Park",
            location_type=Location.LocationType.PARK,
            photo="location_photos/member-priority.jpg",
        )
        self.assertIn("location_photos/member-priority.jpg", location.display_photo_url)
        self.assertFalse(location.uses_default_photo)
