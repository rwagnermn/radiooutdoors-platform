from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Adventure, JournalContact, JournalEntry, Location, MemberProfile


class JournalContactPathAnimationTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("animation-owner", password="test")
        MemberProfile.objects.create(user=self.owner, callsign="W0ANIM", callsign_verified=True)
        self.location = Location.objects.create(
            name="Animation Park", created_by=self.owner,
            latitude="44.100000", longitude="-93.200000",
        )
        self.adventure = Adventure.objects.create(
            owner=self.owner, title="Animation Adventure", operating_callsign="W0ANIM", is_public=True,
        )
        self.journal = JournalEntry.objects.create(
            adventure=self.adventure, location=self.location, title="Animation Journal",
            latitude=self.location.latitude, longitude=self.location.longitude, is_public=True,
        )
        for index, coordinates in enumerate(((40, -75), (41, -76), (0, 0))):
            JournalContact.objects.create(
                journal_entry=self.journal, qso_date="2026-08-21", callsign=f"K{index}TEST",
                latitude=coordinates[0], longitude=coordinates[1], fingerprint=f"animation-{index}",
            )
        self.url = reverse("adventure_contact_geography", args=[self.adventure.slug])

    def test_only_journal_flat_map_opts_into_animation_with_eligible_paths(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'data-contact-path-animation="true"')
        self.assertEqual(response.context["contact_map"]["path_count"], 2)
        self.assertEqual(len(response.context["contact_map"]["contacts"]), 2)
        self.assertNotContains(response, '"latitude": 0.0')
        self.assertNotContains(response, '"longitude": 0.0')

        adventure_map = self.client.get(reverse("adventure_contacts", args=[self.adventure.slug]))
        self.assertNotContains(adventure_map, 'data-contact-path-animation="true"')

    def test_animation_controller_is_single_sequential_and_lifecycle_safe(self):
        source = (Path(settings.BASE_DIR) / "static" / "js" / "contact-map.js").read_text(encoding="utf-8")
        self.assertEqual(source.count('ball = document.createElement("div")'), 1)
        self.assertIn("const CONTACT_PATH_LEG_MS = 500", source)
        self.assertIn("const cycleTime = CONTACT_PATH_LEG_MS * 2", source)
        self.assertIn("pathIndex = (pathIndex + 1) % paths.length", source)
        self.assertIn("requestAnimationFrame(tick)", source)
        self.assertNotIn("setInterval(", source)
        self.assertIn('matchMedia("(prefers-reduced-motion: reduce)")', source)
        self.assertIn('document.addEventListener("visibilitychange"', source)
        self.assertIn('window.addEventListener("pagehide", destroy', source)
        self.assertIn("interpolateGreatCircle(paths[pathIndex].start, paths[pathIndex].end, fraction)", source)
        self.assertIn("if (animation) animation.reset([])", source)

    def test_paths_markers_and_map_type_control_remain_enabled(self):
        source = (Path(settings.BASE_DIR) / "static" / "js" / "contact-map.js").read_text(encoding="utf-8")
        self.assertIn("mapTypeControl: true", source)
        self.assertIn("new google.maps.Polyline", source)
        self.assertIn("new google.maps.marker.AdvancedMarkerElement", source)
        css = (Path(settings.BASE_DIR) / "static" / "css" / "style.css").read_text(encoding="utf-8")
        self.assertIn(".journal-contact-path-ball", css)
        self.assertIn("border:0", css)
        self.assertIn("background:#ffd000", css)
        self.assertIn("box-shadow:none", css)
        self.assertIn("pointer-events:none", css)
        self.assertIn('const CONTACT_PATH_COLOR = "#D9DDE1"', source)
        self.assertIn("CONTACT_PATH_STROKE_WIDTH", source)
        self.assertIn("strokeOpacity: 1", source)
        self.assertIn("strokeWeight: CONTACT_PATH_STROKE_WIDTH", source)
        self.assertIn("point.x - 1", source)

        main_map = self.client.get(reverse("map_explorer"))
        self.assertNotContains(main_map, "journal-contact-path-ball")
        self.assertNotContains(main_map, "data-contact-path-animation")

    def test_private_journal_is_excluded_from_public_adventure_geography(self):
        self.journal.is_public = False
        self.journal.save(update_fields=["is_public"])
        public = self.client.get(self.url)
        self.assertEqual(public.status_code, 200)
        self.assertNotContains(public, "Animation Journal")
        self.assertNotContains(public, "K0TEST")
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url).status_code, 200)
