(function () {
  "use strict";

  const activeMaps = new WeakSet();
  const CONTACT_PATH_STROKE_WIDTH = 4;
  const CONTACT_PATH_COLOR = "#e47b08";

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
    const map = new google.maps.Map(container, { center: initialCenter, zoom: 4, minZoom: 2, mapTypeControl: false, fullscreenControl: true, streetViewControl: false, mapId: "DEMO_MAP_ID" });
    const infoWindow = new google.maps.InfoWindow();

    const controls = container.closest(".adventure-contact-map-section");
    const filter = (name) => controls.querySelector(`[data-contact-filter="${name}"]`);
    const count = controls.querySelector("[data-contact-map-count]");
    const lineNote = controls.querySelector("[data-contact-map-line-note]");
    let markers = [];
    let lines = [];

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

    function visibleOrigins() {
      const journal = filter("journal").value;
      return origins.filter(item => !journal || String(item.journal_id) === journal);
    }

    function render() {
      clearRendered();
      const visible = visibleContacts();
      const currentOrigins = visibleOrigins();
      count.textContent = visible.length;
      const groups = new Map();
      visible.forEach((contact) => {
        const key = `${Number(contact.latitude).toFixed(6)},${Number(contact.longitude).toFixed(6)}`;
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(contact);
      });
      const positions = currentOrigins.map(item => ({ lat: item.latitude, lng: item.longitude }));
      currentOrigins.forEach(item => {
        const originPin = new google.maps.marker.PinElement({ background: "#d86a1c", borderColor: "#ffffff", glyphColor: "#ffffff", glyph: "J", scale: 1.15 });
        markers.push(new google.maps.marker.AdvancedMarkerElement({ map, position: { lat: item.latitude, lng: item.longitude }, title: `${item.label || "Journal Location"}: ${item.name}`, content: originPin.element }));
      });
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
      if (currentOrigins.length && filter("lines").checked) {
        const lineContacts = data.line_limit ? visible.slice(0, data.line_limit) : visible;
        const pathContacts = lineContacts.filter(contact => contact.origin);
        pathContacts.forEach((contact) => lines.push(new google.maps.Polyline({ map, path: [{ lat: contact.origin.latitude, lng: contact.origin.longitude }, { lat: contact.latitude, lng: contact.longitude }], geodesic: true, strokeColor: CONTACT_PATH_COLOR, strokeOpacity: 1, strokeWeight: CONTACT_PATH_STROKE_WIDTH })));
        if (data.line_limit && visible.length > data.line_limit) {
          lineNote.hidden = false;
          lineNote.textContent = `Showing the first ${data.line_limit} contact paths. All ${visible.length} mapped contacts remain visible.`;
        } else lineNote.hidden = true;
      } else {
        lineNote.hidden = true;
      }
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
