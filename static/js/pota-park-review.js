(function () {
    "use strict";
    window.initPotaParkReview = function () {
        document.querySelectorAll("[data-pota-park-map]").forEach(async function (element) {
            const cell = element.closest("td");
            const row = element.closest("tr");
            const resolution = row.querySelector("[data-pota-resolution]");
            const providerInput = cell.querySelector("[data-pota-provider-input]");
            const providerDisplay = cell.querySelector("[data-pota-provider-display]");
            const controller = await window.RadioOutdoorsEditablePinMap.create({
                mapElement: element,
                latInput: document.getElementById(element.dataset.latitudeInput),
                lngInput: document.getElementById(element.dataset.longitudeInput),
                removeButton: document.getElementById(element.dataset.removeButton),
                statusElement: document.getElementById(element.dataset.status),
                coordinateDisplay: document.getElementById(element.dataset.coordinates),
                pinColor: "#f28c28", pinGlyph: "P", pinTitle: "Approximate POTA park location",
                placedMessage: "Approximate park location—review or move this pin.",
                removedMessage: "Park location not found—place pin by clicking the map."
            });
            const candidate = cell.querySelector("[data-pota-candidate]");
            if (candidate) candidate.addEventListener("change", function () {
                const option = candidate.options[candidate.selectedIndex];
                controller.place({lat: option.dataset.latitude, lng: option.dataset.longitude}, true);
                providerInput.value = option.dataset.providerName || "";
                if (providerDisplay) providerDisplay.textContent = providerInput.value;
            });
            const accept = cell.querySelector("[data-pota-accept]");
            if (accept) accept.addEventListener("click", function () {
                resolution.value = "create";
                document.getElementById(element.dataset.status).textContent = "General Location accepted. You may still move the pin before importing.";
            });
        });
    };
}());
