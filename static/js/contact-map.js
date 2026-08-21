(function () {
  "use strict";

  const activeMaps = new WeakSet();
  const CONTACT_PATH_LEG_MS = 500;
  const CONTACT_PATH_STROKE_WIDTH = 2;
  const CONTACT_PATH_COLOR = "#D9DDE1";

  function interpolateGreatCircle(start, end, fraction) {
    const radians = value => value * Math.PI / 180;
    const degrees = value => value * 180 / Math.PI;
    const startLat = radians(start.lat), startLng = radians(start.lng);
    const endLat = radians(end.lat), endLng = radians(end.lng);
    const cosine = Math.sin(startLat) * Math.sin(endLat) + Math.cos(startLat) * Math.cos(endLat) * Math.cos(endLng - startLng);
    const angle = Math.acos(Math.max(-1, Math.min(1, cosine)));
    if (!angle) return { lat: start.lat, lng: start.lng };
    const denominator = Math.sin(angle);
    const a = Math.sin((1 - fraction) * angle) / denominator;
    const b = Math.sin(fraction * angle) / denominator;
    const x = a * Math.cos(startLat) * Math.cos(startLng) + b * Math.cos(endLat) * Math.cos(endLng);
    const y = a * Math.cos(startLat) * Math.sin(startLng) + b * Math.cos(endLat) * Math.sin(endLng);
    const z = a * Math.sin(startLat) + b * Math.sin(endLat);
    return { lat: degrees(Math.atan2(z, Math.sqrt(x * x + y * y))), lng: degrees(Math.atan2(y, x)) };
  }

  function createPathAnimation(map, container) {
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let paths = [], pathIndex = 0, elapsed = 0, previousTime = null, frame = null, overlay = null, ball = null, stopped = false, active = window.radioOutdoorsContactProjection === "flat";

    function removeBall() {
      if (overlay) overlay.setMap(null);
      overlay = null;
      ball = null;
      container.dataset.contactAnimationBallCount = "0";
    }
    function cancelFrame() {
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null;
      previousTime = null;
    }
    function ensureBall() {
      if (ball || reducedMotion.matches || !paths.length) return;
      ball = document.createElement("div");
      ball.className = "journal-contact-path-ball";
      ball.style.width = `${CONTACT_PATH_STROKE_WIDTH}px`;
      ball.style.height = `${CONTACT_PATH_STROKE_WIDTH}px`;
      ball.setAttribute("aria-hidden", "true");
      overlay = new google.maps.OverlayView();
      overlay.onAdd = () => overlay.getPanes().overlayLayer.appendChild(ball);
      overlay.draw = () => {};
      overlay.onRemove = () => { if (ball) ball.remove(); };
      overlay.setMap(map);
      container.dataset.contactAnimationBallCount = "1";
    }
    function placeBall(position) {
      if (!overlay || !ball) return;
      const projection = overlay.getProjection();
      if (!projection) return;
      const point = projection.fromLatLngToDivPixel(new google.maps.LatLng(position.lat, position.lng));
      if (point) ball.style.transform = `translate(${point.x - 1}px,${point.y - 1}px)`;
    }
    function tick(time) {
      frame = null;
      if (stopped || !active || reducedMotion.matches || document.hidden || !paths.length) return;
      if (previousTime === null) previousTime = time;
      elapsed += Math.min(time - previousTime, 100);
      previousTime = time;
      const cycleTime = CONTACT_PATH_LEG_MS * 2;
      while (elapsed >= cycleTime) {
        elapsed -= cycleTime;
        pathIndex = (pathIndex + 1) % paths.length;
      }
      const outbound = elapsed <= CONTACT_PATH_LEG_MS;
      const legProgress = outbound ? elapsed / CONTACT_PATH_LEG_MS : (elapsed - CONTACT_PATH_LEG_MS) / CONTACT_PATH_LEG_MS;
      const fraction = outbound ? legProgress : 1 - legProgress;
      placeBall(interpolateGreatCircle(paths[pathIndex].start, paths[pathIndex].end, fraction));
      container.dataset.contactAnimationPathIndex = String(pathIndex);
      container.dataset.contactAnimationDirection = outbound ? "outbound" : "return";
      frame = requestAnimationFrame(tick);
    }
    function start() {
      if (stopped || !active || reducedMotion.matches || document.hidden || !paths.length) return;
      ensureBall();
      if (frame === null) frame = requestAnimationFrame(tick);
    }
    function reset(nextPaths) {
      cancelFrame();
      paths = nextPaths;
      pathIndex = 0;
      elapsed = 0;
      container.dataset.contactAnimationPathCount = String(paths.length);
      if (!paths.length || reducedMotion.matches) removeBall();
      else start();
    }
    function setActive(nextActive) {
      active = nextActive;
      if (!active) { cancelFrame(); removeBall(); }
      else start();
    }
    function motionChanged() {
      if (reducedMotion.matches) { cancelFrame(); removeBall(); }
      else start();
    }
    function visibilityChanged() {
      if (document.hidden) cancelFrame();
      else start();
    }
    function projectionChanged(event) { setActive(event.detail === "flat"); }
    function destroy() {
      stopped = true;
      cancelFrame();
      removeBall();
      document.removeEventListener("visibilitychange", visibilityChanged);
      window.removeEventListener("pagehide", destroy);
      window.removeEventListener("contact-geography-projection", projectionChanged);
      reducedMotion.removeEventListener("change", motionChanged);
    }
    document.addEventListener("visibilitychange", visibilityChanged);
    window.addEventListener("pagehide", destroy, { once: true });
    window.addEventListener("contact-geography-projection", projectionChanged);
    reducedMotion.addEventListener("change", motionChanged);
    return { reset, destroy, setActive };
  }

  function textElement(tag, text, className) {
    const element = document.createElement(tag);
    element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  function popupContent(group) {
    const wrapper = document.createElement("div");
    wrapper.className = "contact-map-popup";
    wrapper.append(textElement("strong", group.length === 1 ? group[0].callsign : `${group.length} contacts`));
    group.slice(0, 20).forEach((contact) => {
      const item = document.createElement("div");
      item.className = "contact-map-popup-item";
      const details = [contact.callsign, contact.date, contact.time, contact.band, contact.frequency, contact.mode, contact.grid_square, contact.state, contact.country, contact.journal].filter(Boolean);
      item.append(textElement("span", details.join(" · ")));
      item.append(textElement("small", contact.coordinate_source));
      wrapper.append(item);
    });
    if (group.length > 20) wrapper.append(textElement("p", `And ${group.length - 20} more contacts at this position.`));
    return wrapper;
  }

  function initializeMap(container) {
    if (activeMaps.has(container) || !window.google || !google.maps || !google.maps.marker) return;
    const dataNode = document.getElementById(container.dataset.mapDataId);
    if (!dataNode) return;
    const data = JSON.parse(dataNode.textContent);
    if (!data.available || !data.has_map_points) return;
    activeMaps.add(container);

    const origins = (data.origins || (data.origin ? [data.origin] : [])).map(item => ({ ...item, lat: item.latitude, lng: item.longitude }));
    const origin = origins.length ? { lat: origins[0].latitude, lng: origins[0].longitude } : null;
    const firstContact = data.contacts[0];
    const initialCenter = origin || { lat: firstContact.latitude, lng: firstContact.longitude };
    const map = new google.maps.Map(container, { center: initialCenter, zoom: 4, minZoom: 2, mapTypeControl: true, fullscreenControl: true, streetViewControl: false, mapId: "DEMO_MAP_ID" });
    const infoWindow = new google.maps.InfoWindow();
    origins.forEach(item => {
      const originPin = new google.maps.marker.PinElement({ background: "#d86a1c", borderColor: "#ffffff", glyphColor: "#ffffff", glyph: "J", scale: 1.15 });
      new google.maps.marker.AdvancedMarkerElement({ map, position: { lat: item.latitude, lng: item.longitude }, title: `${item.label || "Journal Location"}: ${item.name}`, content: originPin.element });
    });

    const controls = container.closest(".adventure-contact-map-section");
    const filter = (name) => controls.querySelector(`[data-contact-filter="${name}"]`);
    const count = controls.querySelector("[data-contact-map-count]");
    const lineNote = controls.querySelector("[data-contact-map-line-note]");
    let markers = [];
    let lines = [];
    let grayLineOverlays = [];
    const animation = origins.length && container.dataset.contactPathAnimation === "true" ? createPathAnimation(map, container) : null;
    const baseMapButtons = document.querySelectorAll("[data-contact-basemap]");
    const displayButtons = document.querySelectorAll("[data-journal-display]");
    const setPressed = (buttons, value, key) => buttons.forEach(button => button.setAttribute("aria-pressed", String(button.dataset[key] === value)));
    baseMapButtons.forEach(button => button.addEventListener("click", () => {
      map.setMapTypeId(button.dataset.contactBasemap);
      setPressed(baseMapButtons, button.dataset.contactBasemap, "contactBasemap");
    }));
    displayButtons.forEach(button => button.addEventListener("click", () => {
      const night = button.dataset.journalDisplay === "night";
      map.setOptions({ styles: night ? [
        { elementType: "geometry", stylers: [{ color: "#1d2630" }] },
        { elementType: "labels.text.fill", stylers: [{ color: "#d7dde5" }] },
        { elementType: "labels.text.stroke", stylers: [{ color: "#111820" }] },
      ] : null });
    }));
    const grayButton = document.querySelector("[data-journal-gray-line]");
    if (grayButton) grayButton.addEventListener("click", () => {
      grayLineOverlays.forEach(overlay => overlay.setMap(null));
      grayLineOverlays = [];
      const enabled = grayButton.getAttribute("aria-pressed") === "true";
      const helper = window.RadioOutdoorsJournalGlobe;
      if (!enabled || !helper) return;
      const features = helper.grayLineGeoJSON(new Date()).features;
      const night = features.find(feature => feature.properties.kind === "night");
      const terminator = features.find(feature => feature.properties.kind === "terminator");
      if (night) grayLineOverlays.push(new google.maps.Polygon({ map, paths: night.geometry.coordinates[0].map(point => ({ lat: point[1], lng: point[0] })), fillColor: "#03111f", fillOpacity: .34, strokeOpacity: 0, clickable: false }));
      if (terminator) grayLineOverlays.push(new google.maps.Polyline({ map, path: terminator.geometry.coordinates.map(point => ({ lat: point[1], lng: point[0] })), geodesic: false, strokeColor: "#ffe39b", strokeOpacity: .9, strokeWeight: 2, clickable: false }));
    });

    function clearRendered() {
      markers.forEach((marker) => { marker.map = null; });
      lines.forEach((line) => line.setMap(null));
      markers = [];
      lines = [];
    }

    function visibleContacts() {
      const journal = filter("journal").value;
      const band = filter("band").value;
      const mode = filter("mode").value;
      const fromDate = filter("from-date").value;
      const toDate = filter("to-date").value;
      return data.contacts.filter((contact) =>
        (!journal || String(contact.journal_id) === journal) &&
        (!band || contact.band === band) &&
        (!mode || contact.mode === mode) &&
        (!fromDate || contact.date >= fromDate) &&
        (!toDate || contact.date <= toDate)
      );
    }

    function render() {
      clearRendered();
      const visible = visibleContacts();
      count.textContent = visible.length;
      const groups = new Map();
      visible.forEach((contact) => {
        const key = `${Number(contact.latitude).toFixed(6)},${Number(contact.longitude).toFixed(6)}`;
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(contact);
      });
      const positions = origins.map(item => ({ lat: item.latitude, lng: item.longitude }));
      groups.forEach((group) => {
        const first = group[0];
        const position = { lat: first.latitude, lng: first.longitude };
        positions.push(position);
        const grouped = group.length > 1;
        const pin = new google.maps.marker.PinElement({
          background: first.approximate ? "#d7a328" : (grouped ? "#5b3f92" : "#1769aa"),
          borderColor: "#ffffff",
          glyphColor: "#ffffff",
          glyph: grouped ? String(Math.min(group.length, 99)) : "C",
          scale: grouped ? 1.18 : 1,
        });
        const marker = new google.maps.marker.AdvancedMarkerElement({ map, position, title: grouped ? `${group.length} contacts at this position` : first.callsign, content: pin.element });
        marker.addListener("click", () => { infoWindow.setContent(popupContent(group)); infoWindow.open({ map, anchor: marker }); });
        markers.push(marker);
      });
      if (origins.length && filter("lines").checked) {
        const lineContacts = data.line_limit ? visible.slice(0, data.line_limit) : visible;
        const pathContacts = lineContacts.filter(contact => contact.origin);
        pathContacts.forEach((contact) => lines.push(new google.maps.Polyline({ map, path: [{ lat: contact.origin.latitude, lng: contact.origin.longitude }, { lat: contact.latitude, lng: contact.longitude }], geodesic: true, strokeColor: CONTACT_PATH_COLOR, strokeOpacity: 1, strokeWeight: CONTACT_PATH_STROKE_WIDTH })));
        if (animation) animation.reset(pathContacts.map(contact => ({ start: { lat: contact.origin.latitude, lng: contact.origin.longitude }, end: { lat: contact.latitude, lng: contact.longitude } })));
        if (data.line_limit && visible.length > data.line_limit) {
          lineNote.hidden = false;
          lineNote.textContent = `Showing the first ${data.line_limit} contact paths. All ${visible.length} mapped contacts remain visible.`;
        } else lineNote.hidden = true;
      } else {
        lineNote.hidden = true;
        if (animation) animation.reset([]);
      }
      window.dispatchEvent(new CustomEvent("contact-geography-filter-change", { detail: { visibleIds: visible.map(contact => contact.id) } }));
      radioOutdoorsFitMap(map, positions, 32, 14);
    }

    controls.querySelectorAll("[data-contact-filter]").forEach((control) => control.addEventListener("change", render));
    render();
  }

  window.initRadioOutdoorsContactMaps = function () {
    document.querySelectorAll("[data-contact-map]").forEach(initializeMap);
  };
  document.addEventListener("DOMContentLoaded", () => {
    if (window.google && google.maps && google.maps.marker) window.initRadioOutdoorsContactMaps();
  });
})();
