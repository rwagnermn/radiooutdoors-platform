(function () {
  "use strict";
  const initialized = new WeakSet();

  function popupContent(name) {
    const wrapper = document.createElement("div");
    wrapper.className = "map-popup";
    const title = document.createElement("strong");
    title.textContent = name;
    const label = document.createElement("span");
    label.textContent = "Location";
    wrapper.append(title, label);
    return wrapper;
  }

  function initialize(container) {
    if (initialized.has(container) || !window.google || !google.maps || !google.maps.marker) return;
    const dataNode = document.getElementById(container.dataset.mapDataId);
    if (!dataNode) return;
    const point = JSON.parse(dataNode.textContent);
    const position = {lat: point.latitude, lng: point.longitude};
    const map = new google.maps.Map(container, radioOutdoorsMapOptions({
      center: position, zoom: 14, mapId: "DEMO_MAP_ID",
      mapTypeControl: true, streetViewControl: true,
      fullscreenControl: true, gestureHandling: "cooperative"
    }));
    const pin = new google.maps.marker.PinElement({
      background: "#277a45", borderColor: "#ffffff",
      glyphColor: "#ffffff", glyph: "L", scale: 1.25
    });
    const marker = new google.maps.marker.AdvancedMarkerElement({
      map, position, title: point.name, content: pin.element, gmpClickable: true
    });
    const infoWindow = new google.maps.InfoWindow({content: popupContent(point.name)});
    marker.addListener("click", function () { infoWindow.open({map, anchor: marker}); });
    initialized.add(container);
  }

  window.initRadioOutdoorsSingleLocationMaps = function () {
    document.querySelectorAll("[data-single-location-map]").forEach(initialize);
    if (window.initRadioOutdoorsContactMaps) window.initRadioOutdoorsContactMaps();
  };
  document.addEventListener("DOMContentLoaded", function () {
    if (window.google && google.maps && google.maps.marker) window.initRadioOutdoorsSingleLocationMaps();
  });
})();
