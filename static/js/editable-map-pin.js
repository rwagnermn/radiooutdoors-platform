(function () {
    "use strict";

    function validCoordinates(lat, lng) {
        return Number.isFinite(lat) && Number.isFinite(lng)
            && lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180;
    }

    function readCoordinates(latInput, lngInput) {
        const lat = Number.parseFloat(latInput.value);
        const lng = Number.parseFloat(lngInput.value);
        return validCoordinates(lat, lng) ? {lat: lat, lng: lng} : null;
    }

    async function create(config) {
        const {Map} = await google.maps.importLibrary("maps");
        const {AdvancedMarkerElement, PinElement} =
            await google.maps.importLibrary("marker");
        const initial = readCoordinates(config.latInput, config.lngInput);
        const fallback = config.fallbackCenter || {lat: 39.5, lng: -98.35};
        const map = new Map(config.mapElement, radioOutdoorsMapOptions({
            center: initial || fallback,
            zoom: initial ? 16 : (config.fallbackZoom || 4),
            mapId: "DEMO_MAP_ID",
            streetViewControl: true,
            mapTypeControl: true,
            fullscreenControl: true
        }));
        let marker = null;
        let suppressMapClickUntil = 0;

        function syncRemoveButton(hasPin) {
            if (config.removeButton && config.hideRemoveWhenEmpty) {
                config.removeButton.hidden = !hasPin;
            }
        }

        function updateDisplay(position) {
            if (!config.coordinateDisplay) return;
            config.coordinateDisplay.textContent = position
                ? "Latitude: " + position.lat.toFixed(6)
                    + " · Longitude: " + position.lng.toFixed(6)
                : "No pin placed";
        }

        function setStatus(message, isError) {
            if (!config.statusElement) return;
            config.statusElement.textContent = message;
            config.statusElement.classList.toggle("form-error", Boolean(isError));
        }

        function writeCoordinates(position) {
            config.latInput.value = position.lat.toFixed(6);
            config.lngInput.value = position.lng.toFixed(6);
            updateDisplay(position);
            setStatus(config.placedMessage || "Pin placed. Drag it to adjust.", false);
        }

        function place(position, options) {
            const clean = {lat: Number(position.lat), lng: Number(position.lng)};
            if (!validCoordinates(clean.lat, clean.lng)) return false;
            if (!marker) {
                const pin = new PinElement({
                    background: config.pinColor || "#277a45",
                    borderColor: "#ffffff",
                    glyphColor: "#ffffff",
                    glyph: config.pinGlyph || "L"
                });
                marker = new AdvancedMarkerElement({
                    map: map,
                    position: clean,
                    content: pin.element,
                    title: config.pinTitle || "Editable map pin",
                    gmpDraggable: true
                });
                marker.addListener("dragstart", function () {
                    suppressMapClickUntil = Date.now() + 1000;
                });
                marker.addListener("dragend", function (event) {
                    suppressMapClickUntil = Date.now() + 500;
                    const dragged = event.latLng || marker.position;
                    writeCoordinates({
                        lat: typeof dragged.lat === "function" ? dragged.lat() : dragged.lat,
                        lng: typeof dragged.lng === "function" ? dragged.lng() : dragged.lng
                    });
                });
            } else {
                marker.map = map;
                marker.position = clean;
            }
            writeCoordinates(clean);
            syncRemoveButton(true);
            if (options && options.center) {
                map.panTo(clean);
                map.setZoom(16);
            }
            return true;
        }

        function remove() {
            if (marker) marker.map = null;
            marker = null;
            config.latInput.value = "";
            config.lngInput.value = "";
            updateDisplay(null);
            setStatus(config.removedMessage || "Place New Pin: click the map to place it.", false);
            syncRemoveButton(false);
        }

        function reset() {
            const resetCoordinates = config.getResetCoordinates
                ? config.getResetCoordinates()
                : config.resetCoordinates;
            if (resetCoordinates && validCoordinates(
                Number(resetCoordinates.lat), Number(resetCoordinates.lng)
            )) {
                place(resetCoordinates, {center: true});
            }
        }

        map.addListener("dragstart", function () {
            suppressMapClickUntil = Date.now() + 1000;
        });
        map.addListener("dragend", function () {
            suppressMapClickUntil = Date.now() + 500;
        });
        map.addListener("click", function (event) {
            if (!event.latLng || Date.now() < suppressMapClickUntil) return;
            place({lat: event.latLng.lat(), lng: event.latLng.lng()});
        });

        if (config.removeButton) config.removeButton.addEventListener("click", remove);
        if (config.resetButton) config.resetButton.addEventListener("click", reset);
        if (config.form && config.required) {
            config.form.addEventListener("submit", function (event) {
                if (readCoordinates(config.latInput, config.lngInput)) return;
                event.preventDefault();
                setStatus(config.requiredMessage, true);
                if (config.statusElement) config.statusElement.focus();
            });
        }

        if (initial) place(initial);
        else {
            syncRemoveButton(false);
            updateDisplay(null);
            setStatus(config.emptyMessage || "Click the map to place the pin.", false);
        }

        return {
            map: map,
            place: function (position, center) { return place(position, {center: center}); },
            remove: remove,
            reset: reset,
            coordinates: function () { return readCoordinates(config.latInput, config.lngInput); },
            isEmpty: function () { return !readCoordinates(config.latInput, config.lngInput); },
            matches: function (position) {
                const current = readCoordinates(config.latInput, config.lngInput);
                return Boolean(current && position
                    && Math.abs(current.lat - Number(position.lat)) < 0.0000005
                    && Math.abs(current.lng - Number(position.lng)) < 0.0000005);
            }
        };
    }

    window.RadioOutdoorsEditablePinMap = {create: create};
})();
