(function () {
  "use strict";

  const PREFERENCE_KEY = "radioOutdoors.journalContactMap.v1";
  const DAY_STYLE = "https://tiles.openfreemap.org/styles/liberty";
  const NIGHT_STYLE = "https://tiles.openfreemap.org/styles/dark";
  const GRAY_LINE_INTERVAL = 5 * 60 * 1000;
  const PATH_SOURCE = "journal-contact-paths";
  const PATH_LAYER = "journal-contact-paths";
  const GRAY_SOURCE = "journal-gray-line";
  const GRAY_LAYERS = ["journal-night-hemisphere", "journal-gray-line-band", "journal-terminator"];

  function safePreference() {
    try {
      return JSON.parse(localStorage.getItem(PREFERENCE_KEY) || "{}") || {};
    } catch (_) {
      return {};
    }
  }

  function savePreference(value) {
    try { localStorage.setItem(PREFERENCE_KEY, JSON.stringify(value)); } catch (_) {}
  }

  function toRadians(value) { return value * Math.PI / 180; }
  function toDegrees(value) { return value * 180 / Math.PI; }

  function supportsWebGL() {
    try {
      const canvas = document.createElement("canvas");
      return Boolean(window.WebGLRenderingContext && (
        canvas.getContext("webgl2", { failIfMajorPerformanceCaveat: true }) ||
        canvas.getContext("webgl", { failIfMajorPerformanceCaveat: true })
      ));
    } catch (_) {
      return false;
    }
  }

  function greatCircleCoordinates(start, end, steps) {
    const lat1 = toRadians(start[1]), lon1 = toRadians(start[0]);
    const lat2 = toRadians(end[1]), lon2 = toRadians(end[0]);
    const angular = 2 * Math.asin(Math.sqrt(
      Math.sin((lat2 - lat1) / 2) ** 2 +
      Math.cos(lat1) * Math.cos(lat2) * Math.sin((lon2 - lon1) / 2) ** 2
    ));
    if (!angular) return [start, end];
    const count = Math.max(16, steps || Math.ceil(toDegrees(angular) / 2));
    const sinAngular = Math.sin(angular);
    const points = [];
    for (let index = 0; index <= count; index += 1) {
      const fraction = index / count;
      const a = Math.sin((1 - fraction) * angular) / sinAngular;
      const b = Math.sin(fraction * angular) / sinAngular;
      const x = a * Math.cos(lat1) * Math.cos(lon1) + b * Math.cos(lat2) * Math.cos(lon2);
      const y = a * Math.cos(lat1) * Math.sin(lon1) + b * Math.cos(lat2) * Math.sin(lon2);
      const z = a * Math.sin(lat1) + b * Math.sin(lat2);
      points.push([toDegrees(Math.atan2(y, x)), toDegrees(Math.atan2(z, Math.sqrt(x * x + y * y)))]);
    }
    return points;
  }

  function solarPosition(date) {
    const julian = date.getTime() / 86400000 + 2440587.5;
    const days = julian - 2451545.0;
    const meanLongitude = (280.460 + 0.9856474 * days) % 360;
    const anomaly = toRadians((357.528 + 0.9856003 * days) % 360);
    const eclipticLongitude = toRadians(meanLongitude + 1.915 * Math.sin(anomaly) + 0.020 * Math.sin(2 * anomaly));
    const obliquity = toRadians(23.439 - 0.0000004 * days);
    const declination = Math.asin(Math.sin(obliquity) * Math.sin(eclipticLongitude));
    const rightAscension = Math.atan2(Math.cos(obliquity) * Math.sin(eclipticLongitude), Math.cos(eclipticLongitude));
    const gmst = (280.46061837 + 360.98564736629 * (julian - 2451545.0)) % 360;
    let longitude = toDegrees(rightAscension) - gmst;
    longitude = ((longitude + 540) % 360) - 180;
    return { longitude, declination };
  }

  function grayLineGeoJSON(date) {
    const sun = solarPosition(date);
    const boundary = [];
    for (let longitude = -180; longitude <= 180; longitude += 2) {
      const hourAngle = toRadians(longitude - sun.longitude);
      const latitude = toDegrees(Math.atan2(-Math.cos(hourAngle), Math.tan(sun.declination)));
      boundary.push([longitude, Math.max(-89.9, Math.min(89.9, latitude))]);
    }
    const nightPole = sun.declination >= 0 ? -90 : 90;
    const polygon = boundary.concat([[180, nightPole], [-180, nightPole], boundary[0]]);
    return {
      type: "FeatureCollection",
      features: [
        { type: "Feature", properties: { kind: "night" }, geometry: { type: "Polygon", coordinates: [polygon] } },
        { type: "Feature", properties: { kind: "terminator" }, geometry: { type: "LineString", coordinates: boundary } },
      ],
    };
  }

  function popupNode(contact) {
    const node = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = contact.callsign;
    node.append(title);
    const details = [contact.date, contact.time, contact.band, contact.mode, contact.grid_square, contact.state, contact.country].filter(Boolean);
    if (details.length) {
      const paragraph = document.createElement("p");
      paragraph.textContent = details.join(" · ");
      node.append(paragraph);
    }
    const source = document.createElement("small");
    source.textContent = contact.coordinate_source;
    node.append(source);
    return node;
  }

  function start() {
    const globeElement = document.querySelector("[data-journal-contact-globe]");
    if (!globeElement) return;
    const dataNode = document.getElementById(globeElement.dataset.mapDataId);
    const flatShell = document.querySelector("[data-journal-flat-map-shell]");
    const globeShell = document.querySelector("[data-journal-globe-shell]");
    const status = document.querySelector("[data-journal-globe-status]");
    const liveStatus = document.querySelector("[data-journal-gray-line-status]");
    const utcTime = document.querySelector("[data-journal-globe-utc]");
    const projectionButtons = document.querySelectorAll("[data-journal-projection]");
    const displayButtons = document.querySelectorAll("[data-journal-display]");
    const resetButton = document.querySelector("[data-journal-globe-reset]");
    if (!dataNode || !flatShell || !globeShell) return;
    const data = JSON.parse(dataNode.textContent);
    const preference = safePreference();
    let projection = preference.projection === "flat" ? "flat" : "globe";
    let display = ["day", "night", "gray-line"].includes(preference.display) ? preference.display : "day";
    let map = null;
    let grayTimer = null;
    let styleGeneration = 0;
    let restoredGeneration = -1;
    let overlaysRestoring = false;
    let markersInitialized = false;
    let overlayRestoreCount = 0;
    const markers = [];

    function setPressed(buttons, attribute, value) {
      buttons.forEach((button) => button.setAttribute("aria-pressed", String(button.dataset[attribute] === value)));
    }

    function showFlat(message, persist) {
      projection = "flat";
      globeShell.hidden = true;
      flatShell.hidden = false;
      setPressed(projectionButtons, "journalProjection", projection);
      status.textContent = message || "Flat Map view";
      if (persist !== false) savePreference({ projection, display });
      if (window.initRadioOutdoorsContactMaps) window.initRadioOutdoorsContactMaps();
      if (window.google && google.maps) window.dispatchEvent(new Event("resize"));
    }

    function pathGeoJSON() {
      const origin = [data.origin.longitude, data.origin.latitude];
      return {
        type: "FeatureCollection",
        features: data.contacts.map((contact) => ({
          type: "Feature",
          properties: { contact_id: contact.id, callsign: contact.callsign },
          geometry: { type: "LineString", coordinates: greatCircleCoordinates(origin, [contact.longitude, contact.latitude]) },
        })),
      };
    }

    const authorizedPathData = data.available && data.origin
      ? pathGeoJSON()
      : { type: "FeatureCollection", features: [] };

    function firstSymbolLayerId() {
      const style = map && map.getStyle();
      const layer = style && style.layers && style.layers.find((item) => item.type === "symbol");
      return layer ? layer.id : undefined;
    }

    function addLayerBelowLabels(layer, beforeId) {
      if (beforeId) map.addLayer(layer, beforeId);
      else map.addLayer(layer);
    }

    function markerElement(kind, label, glyph) {
      const element = document.createElement("button");
      element.type = "button";
      element.className = `journal-globe-marker journal-globe-marker-${kind}`;
      element.setAttribute("aria-label", label);
      const head = document.createElement("span");
      head.className = "journal-globe-marker-head";
      head.setAttribute("aria-hidden", "true");
      head.textContent = glyph;
      element.append(head);
      return element;
    }

    function ensureMarkers() {
      if (!map || markersInitialized) return;
      if (data.origin) {
        const originMarker = markerElement("origin", `Journal Location: ${data.origin.name}`, "J");
        markers.push(new maplibregl.Marker({ element: originMarker }).setLngLat([data.origin.longitude, data.origin.latitude]).setPopup(new maplibregl.Popup().setText(`Journal Location: ${data.origin.name}`)).addTo(map));
      }
      data.contacts.forEach((contact) => {
        const element = markerElement("contact", `Contact ${contact.callsign}`, "C");
        markers.push(new maplibregl.Marker({ element }).setLngLat([contact.longitude, contact.latitude]).setPopup(new maplibregl.Popup().setDOMContent(popupNode(contact))).addTo(map));
      });
      markersInitialized = true;
      globeElement.dataset.contactMarkerCount = String(data.contacts.length);
    }

    function syncLegendState() {
      setPressed(projectionButtons, "journalProjection", projection);
      setPressed(displayButtons, "journalDisplay", display);
      liveStatus.hidden = display !== "gray-line";
      globeShell.classList.toggle("journal-globe-night", display === "night" || display === "gray-line");
      status.textContent = projection === "globe"
        ? `Globe view · ${display === "gray-line" ? "Gray Line (live)" : display[0].toUpperCase() + display.slice(1)}`
        : "Flat Map view";
    }

    function ensureGrayLineLayers(now, beforeId) {
      const geojson = grayLineGeoJSON(now);
      const source = map.getSource(GRAY_SOURCE);
      if (source) source.setData(geojson);
      else map.addSource(GRAY_SOURCE, { type: "geojson", data: geojson });
      const layers = [
        { id: GRAY_LAYERS[0], type: "fill", source: GRAY_SOURCE, filter: ["==", ["get", "kind"], "night"], paint: { "fill-color": "#03111f", "fill-opacity": .56 } },
        { id: GRAY_LAYERS[1], type: "line", source: GRAY_SOURCE, filter: ["==", ["get", "kind"], "terminator"], paint: { "line-color": "#c7b06a", "line-width": 10, "line-opacity": .34 } },
        { id: GRAY_LAYERS[2], type: "line", source: GRAY_SOURCE, filter: ["==", ["get", "kind"], "terminator"], paint: { "line-color": "#ffe39b", "line-width": 2, "line-opacity": .9 } },
      ];
      layers.forEach((layer) => {
        if (!map.getLayer(layer.id)) addLayerBelowLabels(layer, beforeId);
      });
      utcTime.textContent = now.toISOString().replace("T", " ").slice(0, 16) + " UTC";
      utcTime.dateTime = now.toISOString();
      globeElement.dataset.grayLineUpdatedAt = now.toISOString();
    }

    function restoreJournalOverlays(generation) {
      if (!map || generation !== styleGeneration || overlaysRestoring) return;
      const alreadyComplete = generation === restoredGeneration
        && map.getSource(PATH_SOURCE)
        && map.getLayer(PATH_LAYER)
        && (display !== "gray-line" || GRAY_LAYERS.every((id) => map.getLayer(id)));
      if (alreadyComplete) return;
      overlaysRestoring = true;
      restoredGeneration = generation;
      try {
        const beforeId = firstSymbolLayerId();
        ensureMarkers();
        if (display === "gray-line") ensureGrayLineLayers(new Date(), beforeId);
        if (authorizedPathData.features.length) {
          if (!map.getSource(PATH_SOURCE)) map.addSource(PATH_SOURCE, { type: "geojson", data: authorizedPathData });
          if (!map.getLayer(PATH_LAYER)) addLayerBelowLabels({
            id: PATH_LAYER, type: "line", source: PATH_SOURCE,
            paint: { "line-color": display === "night" ? "#62d8ff" : "#ff7b25", "line-width": 2.4, "line-opacity": .86 },
          }, beforeId);
          if (beforeId && map.getLayer(PATH_LAYER)) map.moveLayer(PATH_LAYER, beforeId);
        }
        syncLegendState();
        globeElement.dataset.contactPathCount = String(authorizedPathData.features.length);
        globeElement.dataset.contactPathSourceCount = String(map.getSource(PATH_SOURCE) ? 1 : 0);
        globeElement.dataset.contactPathLayerCount = String(map.getStyle().layers.filter((layer) => layer.id === PATH_LAYER).length);
        globeElement.dataset.mapMarkerCount = String(markers.length);
        globeElement.dataset.overlayGeneration = String(generation);
        delete globeElement.dataset.overlayPending;
        overlayRestoreCount += 1;
        globeElement.dataset.overlayRestoreCount = String(overlayRestoreCount);
      } catch (_) {
        restoredGeneration = -1;
        globeElement.dataset.overlayPending = "true";
      } finally {
        overlaysRestoring = false;
      }
    }

    function updateGrayLine(now) {
      if (!map || display !== "gray-line") return;
      try { ensureGrayLineLayers(now, firstSymbolLayerId()); } catch (_) {}
    }

    function clearGrayTimer() {
      if (grayTimer) window.clearInterval(grayTimer);
      grayTimer = null;
    }

    function applyDisplay(nextDisplay) {
      display = nextDisplay;
      clearGrayTimer();
      syncLegendState();
      savePreference({ projection, display });
      if (!map) return;
      styleGeneration += 1;
      globeElement.dataset.requestedStyleGeneration = String(styleGeneration);
      map.setStyle(display === "night" ? NIGHT_STYLE : DAY_STYLE);
      restoreJournalOverlays(styleGeneration);
      if (display === "gray-line") grayTimer = window.setInterval(() => updateGrayLine(new Date()), GRAY_LINE_INTERVAL);
    }

    function resetView() {
      if (!map) return;
      map.jumpTo({ center: initialCenter(), zoom: initialZoom(), bearing: 0, pitch: 0 });
    }

    function initialCenter() {
      if (data.origin) return [data.origin.longitude, data.origin.latitude];
      if (!data.contacts.length) return [0, 0];
      return [
        data.contacts.reduce((sum, contact) => sum + contact.longitude, 0) / data.contacts.length,
        data.contacts.reduce((sum, contact) => sum + contact.latitude, 0) / data.contacts.length,
      ];
    }

    function initialZoom() {
      if (!data.origin) return data.contacts.length > 1 ? 1.25 : 3.2;
      const origin = [data.origin.longitude, data.origin.latitude];
      let maximum = 0;
      data.contacts.forEach((contact) => {
        const path = greatCircleCoordinates(origin, [contact.longitude, contact.latitude], 16);
        maximum = Math.max(maximum, path.length ? path.length - 1 : 0);
      });
      return Math.max(.8, Math.min(3.2, 2.8 - Math.log2(Math.max(1, maximum / 32))));
    }

    function initializeGlobe() {
      if (!data.available || !data.has_map_points) {
        showFlat(data.message || "No Journal contact locations are available to map.", false);
        return;
      }
      if (!window.maplibregl || !supportsWebGL()) {
        showFlat("Flat Map shown because interactive globe rendering is unavailable.", false);
        return;
      }
      try {
        map = new maplibregl.Map({
          container: globeElement,
          style: display === "night" ? NIGHT_STYLE : DAY_STYLE,
          center: initialCenter(),
          zoom: initialZoom(),
          projection: { type: "globe" },
          attributionControl: false,
          canvasContextAttributes: { antialias: true },
        });
        map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
        map.addControl(new maplibregl.FullscreenControl({ container: globeShell }), "top-right");
        map.addControl(new maplibregl.AttributionControl({ compact: false, customAttribution: "OpenFreeMap © OpenMapTiles · Data © OpenStreetMap contributors" }));
        const recordView = () => {
          const center = map.getCenter();
          globeElement.dataset.viewState = `${center.lng.toFixed(4)},${center.lat.toFixed(4)},${map.getZoom().toFixed(3)}`;
        };
        map.on("moveend", recordView);
        map.on("zoomend", recordView);
        recordView();
        const restoreCurrentStyle = () => restoreJournalOverlays(styleGeneration);
        map.on("load", restoreCurrentStyle);
        map.on("style.load", restoreCurrentStyle);
        map.on("styledata", restoreCurrentStyle);
      } catch (_) {
        showFlat("Flat Map shown because interactive globe rendering is unavailable.", false);
      }
    }

    projectionButtons.forEach((button) => button.addEventListener("click", () => {
      const next = button.dataset.journalProjection;
      if (next === "flat") showFlat(null, true);
      else {
        projection = "globe";
        flatShell.hidden = true;
        globeShell.hidden = false;
        setPressed(projectionButtons, "journalProjection", projection);
        status.textContent = `Globe view · ${display === "gray-line" ? "Gray Line (live)" : display[0].toUpperCase() + display.slice(1)}`;
        savePreference({ projection, display });
        if (!map) initializeGlobe();
        else {
          map.resize();
          restoreJournalOverlays(styleGeneration);
        }
      }
    }));
    displayButtons.forEach((button) => button.addEventListener("click", () => applyDisplay(button.dataset.journalDisplay)));
    resetButton.addEventListener("click", resetView);
    setPressed(projectionButtons, "journalProjection", projection);
    setPressed(displayButtons, "journalDisplay", display);
    if (projection === "flat") showFlat();
    else {
      liveStatus.hidden = display !== "gray-line";
      status.textContent = `Globe view · ${display === "gray-line" ? "Gray Line (live)" : display[0].toUpperCase() + display.slice(1)}`;
      initializeGlobe();
      if (display === "gray-line") grayTimer = window.setInterval(() => updateGrayLine(new Date()), GRAY_LINE_INTERVAL);
    }
  }

  window.RadioOutdoorsJournalGlobe = { greatCircleCoordinates, grayLineGeoJSON, solarPosition, supportsWebGL };
  document.addEventListener("DOMContentLoaded", start);
})();
