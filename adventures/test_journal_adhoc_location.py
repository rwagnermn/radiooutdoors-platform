from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Adventure, JournalEntry, Location, MemberProfile


class JournalUnifiedLocationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("journal-owner", password="test")
        MemberProfile.objects.create(user=self.user, callsign="W0JRN", callsign_verified=True, verification_method=MemberProfile.VerificationMethod.QRZ)
        self.other = get_user_model().objects.create_user("other-owner", password="test")
        self.adventure = Adventure.objects.create(owner=self.user, title="Unified Location Adventure", operating_callsign="W0JRN")
        self.existing = Location.objects.create(name="Existing Park", created_by=self.user, latitude="44.100000", longitude="-93.100000")
        self.client.force_login(self.user)
        self.add_url = reverse("add_journal_entry", args=[self.adventure.slug])

    def payload(self, **updates):
        data = {"entry_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"), "status": "open", "is_public": "on", "journal_visibility_present": "1", "location_name": self.existing.name, "location": str(self.existing.pk), "location_source": "existing", "latitude": "44.100000", "longitude": "-93.100000", "operating_callsign": "W0JRN", "body": "Journal note."}
        data.update(updates); return data

    def new_payload(self, **updates):
        data = self.payload(location_name="Near Pike Lake", location="", location_source="typed", latitude="46.123456", longitude="-92.654321")
        data.update(updates); return data

    def test_only_one_visible_location_entry_field(self):
        response = self.client.get(self.add_url)
        self.assertContains(response, 'name="location_name"', count=1)
        self.assertContains(response, 'type="hidden" name="location"', count=1)
        self.assertNotContains(response, 'name="location_mode"')
        self.assertNotContains(response, "Choose an existing Location")
        self.assertNotContains(response, "Create an ad-hoc Location")
        self.assertContains(response, "Start typing to find a Location. Choose a match, or keep what you typed and place the pin manually.")

    def test_existing_radio_outdoors_location_links_with_independent_pin(self):
        self.client.post(self.add_url, self.payload(latitude="44.199999", longitude="-93.299999"))
        entry = JournalEntry.objects.get(); self.existing.refresh_from_db()
        self.assertEqual(entry.location, self.existing)
        self.assertEqual(str(entry.latitude), "44.199999")
        self.assertEqual(str(self.existing.latitude), "44.100000")

    def test_add_defaults_to_previous_journal_location_and_exact_pin(self):
        JournalEntry.objects.create(
            adventure=self.adventure,
            location=self.existing,
            latitude="44.222222",
            longitude="-93.333333",
            operating_callsign="W0JRN",
            body="Previous operating position",
        )

        response = self.client.get(self.add_url)
        form = response.context["form"]

        self.assertEqual(form.initial["location"], self.existing.pk)
        self.assertEqual(form.initial["location_name"], self.existing.name)
        self.assertEqual(str(form.initial["latitude"]), "44.222222")
        self.assertEqual(str(form.initial["longitude"]), "-93.333333")

    def test_photo_collection_journal_is_ignored_for_location_default(self):
        previous = Location.objects.create(
            name="Previous Trailhead",
            created_by=self.user,
            latitude="45.100000",
            longitude="-94.100000",
        )
        JournalEntry.objects.create(
            adventure=self.adventure,
            location=previous,
            latitude="45.111111",
            longitude="-94.222222",
            operating_callsign="W0JRN",
            body="Real journal",
        )
        photo_location = Location.objects.create(
            name="Photo metadata location",
            created_by=self.user,
            latitude="46.000000",
            longitude="-95.000000",
        )
        JournalEntry.objects.create(
            adventure=self.adventure,
            location=photo_location,
            latitude="46.123456",
            longitude="-95.654321",
            operating_callsign="W0JRN",
            body="Adventure photos",
            is_adventure_photo_collection=True,
        )

        form = self.client.get(self.add_url).context["form"]

        self.assertEqual(form.initial["location"], previous.pk)
        self.assertEqual(str(form.initial["latitude"]), "45.111111")
        self.assertEqual(str(form.initial["longitude"]), "-94.222222")

    def test_google_result_creates_and_links_public_location(self):
        self.client.post(self.add_url, self.new_payload(location_name="Pike Lake Park", location_source="google", google_formatted_address="123 Lake Rd, Duluth, MN", google_city="Duluth", google_state="MN", google_country="USA", google_location_type="park"))
        entry = JournalEntry.objects.select_related("location").get()
        self.assertEqual(entry.location.name, "Pike Lake Park")
        self.assertEqual(entry.location.visibility, Location.Visibility.PUBLIC)
        self.assertEqual(entry.location.city, "Duluth")
        self.assertEqual(entry.location.location_type, Location.LocationType.PARK)

    def test_unmatched_custom_name_needs_no_street_address(self):
        self.client.post(self.add_url, self.new_payload())
        location = JournalEntry.objects.select_related("location").get().location
        self.assertEqual(location.name, "Near Pike Lake")
        self.assertEqual(location.street_address, "")

    def test_atomic_failure_rolls_back_new_location(self):
        before = Location.objects.count()
        with patch("core.models.JournalEntry.save", side_effect=RuntimeError("failed")):
            with self.assertRaises(RuntimeError): self.client.post(self.add_url, self.new_payload())
        self.assertEqual(Location.objects.count(), before)

    def test_private_location_is_not_disclosed(self):
        secret = Location.objects.create(name="Secret Cabin", created_by=self.other, visibility=Location.Visibility.PRIVATE, latitude="44.2", longitude="-93.2")
        response = self.client.get(self.add_url)
        self.assertNotContains(response, secret.name)
        self.assertNotIn(secret.pk, {point["id"] for point in response.context["journal_location_choices"]})

    def test_validation_failure_preserves_unified_location_and_journal_values(self):
        response = self.client.post(self.add_url, self.new_payload(body="", location_name="Near Pike Lake"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].data["location_name"], "Near Pike Lake")
        self.assertEqual(Location.objects.count(), 1)

    def test_edit_changes_location_without_modifying_old_record(self):
        entry = JournalEntry.objects.create(adventure=self.adventure, location=self.existing, latitude="44.2", longitude="-93.2", operating_callsign="W0JRN", body="Before")
        self.client.post(reverse("edit_journal_entry", args=[entry.pk]), self.new_payload(location_name="New Ridge", body="After"))
        entry.refresh_from_db(); self.existing.refresh_from_db()
        self.assertEqual(entry.location.name, "New Ridge")
        self.assertEqual(self.existing.name, "Existing Park")

    def test_edit_retains_its_own_location_and_exact_pin(self):
        other_location = Location.objects.create(
            name="Newer Location",
            created_by=self.user,
            latitude="46.000000",
            longitude="-94.000000",
        )
        entry = JournalEntry.objects.create(
            adventure=self.adventure,
            location=self.existing,
            latitude="44.222222",
            longitude="-93.333333",
            operating_callsign="W0JRN",
            body="Entry being edited",
        )
        JournalEntry.objects.create(
            adventure=self.adventure,
            location=other_location,
            latitude="46.111111",
            longitude="-94.222222",
            operating_callsign="W0JRN",
            body="Newer entry",
        )

        form = self.client.get(reverse("edit_journal_entry", args=[entry.pk])).context["form"]

        self.assertEqual(form.initial["location"], self.existing.pk)
        self.assertEqual(str(form.initial["latitude"]), "44.222222")
        self.assertEqual(str(form.initial["longitude"]), "-93.333333")

    def test_map_script_preserves_manual_pin_and_fullscreen(self):
        source = (settings.BASE_DIR / "static" / "js" / "journal-location-map.js").read_text(encoding="utf-8")
        self.assertIn("manuallyMoved", source)
        self.assertIn("draggable: true", source)
        self.assertIn("fullscreenControl: true", source)
        self.assertIn("RadioOutdoorsLocationAutocomplete.attach", source)

    def test_adventure_top_add_journal_action_is_authorized(self):
        owner = self.client.get(self.adventure.get_absolute_url())
        self.assertContains(owner, reverse("add_journal_entry", args=[self.adventure.slug]))
        self.assertContains(
            owner,
            'class="button-primary adventure-journal-add-action">+ Add Journal Entry</a>',
            html=False,
        )
        self.client.force_login(self.other)
        visitor = self.client.get(self.adventure.get_absolute_url())
        self.assertNotContains(visitor, reverse("add_journal_entry", args=[self.adventure.slug]))

    def test_journal_photos_are_compact_and_mobile_responsive(self):
        css = (settings.BASE_DIR / "static" / "css" / "style.css").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns:repeat(auto-fill,minmax(140px,160px))", css)
        self.assertIn(".journal-story-page .journal-view-photos .journal-photo{max-width:160px}", css)
        self.assertIn("grid-template-columns:minmax(0,1fr);width:100%;max-width:100%", css)
        self.assertIn(".journal-story-page .journal-view-photos .journal-photo,", css)

        template = (
            settings.BASE_DIR / "templates" / "adventures" / "journal_entry_detail.html"
        ).read_text(encoding="utf-8")
        self.assertIn('class="journal-photo-viewer-trigger"', template)
        self.assertIn('data-full-src="{{ photo.image.url }}', template)
        self.assertIn("at original size", template)

    def test_cover_and_embedded_map_dimensions_are_compact(self):
        css = (settings.BASE_DIR / "static" / "css" / "style.css").read_text(encoding="utf-8")

        self.assertIn("grid-template-columns: minmax(0, 68.5%) minmax(240px, 31.5%)", css)
        self.assertIn("height: clamp(210px, 21vw, 255px)", css)
        self.assertIn("grid-template-columns:minmax(360px,440px) minmax(0,1fr)", css)
        self.assertIn(".journal-story-page .single-location-map{width:400px;height:400px", css)
        self.assertIn(".embedded-contact-map-layout>.contact-map-legend{grid-row:4}", css)
        self.assertIn("@media(max-width:900px)", css)

        adventure_template = (
            settings.BASE_DIR / "templates" / "adventures" / "adventure_detail.html"
        ).read_text(encoding="utf-8")
        contact_template = (
            settings.BASE_DIR / "templates" / "adventures" / "_contact_map.html"
        ).read_text(encoding="utf-8")
        self.assertNotIn("embedded-detail-map-layout adventure-journal-map-layout", adventure_template)
        self.assertIn('class="adventure-dashboard-map"', adventure_template)
        self.assertIn('google.maps.event.trigger(map,"resize")', adventure_template)
        self.assertIn("embedded-detail-map-layout embedded-contact-map-layout", contact_template)

    def test_saved_coordinates_serialize_to_journal_adventure_and_main_maps(self):
        self.client.post(self.add_url, self.new_payload(latitude="46.222222", longitude="-92.333333"))
        entry = JournalEntry.objects.get()
        for response in (self.client.get(reverse("journal_entry_detail", args=[entry.pk])), self.client.get(self.adventure.get_absolute_url()), self.client.get(reverse("map_explorer"))):
            self.assertContains(response, '"latitude": 46.222222')
            self.assertContains(response, '"longitude": -92.333333')
