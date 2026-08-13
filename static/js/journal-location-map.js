(function () {
  "use strict";
  let map, marker, manuallyMoved = false, nearestMatch = null;
  const byId = (id) => document.getElementById(id);
  const number = (value) => { const parsed = parseFloat(value); return Number.isFinite(parsed) ? parsed : null; };
  const radians = (degrees) => degrees * Math.PI / 180;
  function milesBetween(a, b) {
    const dLat = radians(b.latitude - a.lat), dLng = radians(b.longitude - a.lng);
    const value = Math.sin(dLat / 2) ** 2 + Math.cos(radians(a.lat)) * Math.cos(radians(b.latitude)) * Math.sin(dLng / 2) ** 2;
    return 3958.8 * 2 * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value));
  }
  function write(position) { byId("id_latitude").value = position.lat.toFixed(6); byId("id_longitude").value = position.lng.toFixed(6); }
  function clearExternalSelection() { byId("id_location").value = ""; byId("id_location_source").value = "typed"; }
  function showNearest(position, points) {
    const panel = byId("journal-nearest-location");
    if (byId("id_location").value) { panel.hidden = true; return; }
    nearestMatch = points.filter((point) => number(point.latitude) !== null && number(point.longitude) !== null)
      .map((point) => Object.assign({}, point, {distance: milesBetween(position, point)})).sort((a, b) => a.distance - b.distance)[0] || null;
    if (!nearestMatch || nearestMatch.distance > 25) { panel.hidden = true; return; }
    panel.querySelector("[data-nearest-location-message]").textContent = `Nearby Radio Outdoors Location: ${nearestMatch.name} (${nearestMatch.distance.toFixed(1)} miles away).`;
    panel.hidden = false;
  }
  function place(position, points, center) {
    if (!position || number(position.lat) === null || number(position.lng) === null) return;
    const clean = {lat: number(position.lat), lng: number(position.lng)};
    if (!map) {
      map = new google.maps.Map(byId("journal-pin-map"), {center: clean, zoom: 14, mapTypeControl: true, streetViewControl: true, fullscreenControl: true});
      marker = new google.maps.Marker({position: clean, map, draggable: true, title: "This Journal's exact operating position"});
      marker.addListener("dragend", () => { manuallyMoved = true; const current = {lat: marker.getPosition().lat(), lng: marker.getPosition().lng()}; write(current); showNearest(current, points); });
      map.addListener("click", (event) => { manuallyMoved = true; const current = {lat: event.latLng.lat(), lng: event.latLng.lng()}; marker.setPosition(current); write(current); showNearest(current, points); });
    } else { marker.setPosition(clean); if (center) { map.setCenter(clean); map.setZoom(14); } }
    write(clean); showNearest(clean, points);
  }
  function selectExisting(point, points) {
    byId("id_location_name").value = point.name; byId("id_location").value = String(point.id); byId("id_location_source").value = "existing";
    manuallyMoved = false; place({lat: point.latitude, lng: point.longitude}, points, true); byId("journal-location-results").hidden = true;
  }
  function renderRadioOutdoorsMatches(points) {
    const input = byId("id_location_name"), results = byId("journal-location-results"), query = input.value.trim().toLowerCase();
    if (byId("id_location").value && points.find((point) => String(point.id) === byId("id_location").value)?.name !== input.value) clearExternalSelection();
    const matches = query.length < 2 ? [] : points.filter((point) => point.name.toLowerCase().includes(query)).slice(0, 8);
    results.replaceChildren();
    matches.forEach((point) => { const button = document.createElement("button"); button.type = "button"; button.setAttribute("role", "option"); button.innerHTML = `<strong>${point.name}</strong><small>Radio Outdoors Location</small>`; button.addEventListener("click", () => selectExisting(point, points)); results.append(button); });
    results.hidden = !matches.length;
  }
  window.initJournalLocationMap = async function () {
    const input = byId("id_location_name"), data = byId("journal-location-choice-data"), defaultsNode = byId("journal-map-defaults");
    if (!input || !data || !defaultsNode || !window.google) return;
    const points = JSON.parse(data.textContent), defaults = JSON.parse(defaultsNode.textContent), selected = points.find((point) => String(point.id) === byId("id_location").value);
    const saved = {lat: number(byId("id_latitude").value), lng: number(byId("id_longitude").value)};
    const fallback = defaults.fallback || {latitude: 39.5, longitude: -98.35, zoom: 4};
    if (saved.lat !== null && saved.lng !== null) place(saved, points, true);
    else if (selected) place({lat: selected.latitude, lng: selected.longitude}, points, true);
    else {
      place({lat: fallback.latitude, lng: fallback.longitude}, points, true); map.setZoom(fallback.zoom || 4);
      const useServerFallback = () => { if (!manuallyMoved) { const candidate = defaults.recent || defaults.nearby; if (candidate) place({lat: candidate.latitude, lng: candidate.longitude}, points, true); } };
      if (navigator.geolocation) navigator.geolocation.getCurrentPosition((position) => { if (!manuallyMoved) place({lat: position.coords.latitude, lng: position.coords.longitude}, points, true); }, useServerFallback, {enableHighAccuracy: true, timeout: 6000, maximumAge: 300000}); else useServerFallback();
    }
    input.addEventListener("input", () => { renderRadioOutdoorsMatches(points); if (!byId("id_location").value) byId("id_location_source").value = "typed"; });
    await RadioOutdoorsLocationAutocomplete.attach(input, (result) => {
      input.value = result.name; byId("id_location").value = ""; byId("id_location_source").value = "google";
      byId("id_google_formatted_address").value = result.formattedAddress; byId("id_google_city").value = result.address.city;
      byId("id_google_state").value = result.address.state; byId("id_google_country").value = result.address.country; byId("id_google_location_type").value = result.type;
      if (!manuallyMoved) place(result.position, points, true); byId("journal-location-results").hidden = true;
    });
    byId("journal-nearest-location").querySelector("[data-use-nearest-location]").addEventListener("click", () => { if (nearestMatch) selectExisting(nearestMatch, points); });
    byId("journal-nearest-location").querySelector("[data-keep-adhoc-location]").addEventListener("click", () => { byId("journal-nearest-location").hidden = true; nearestMatch = null; });
  };
})();
