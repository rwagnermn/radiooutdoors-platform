(function () {
    "use strict";

    window.radioOutdoorsMapOptions = function (options) {
        return Object.assign({}, options, {
            gestureHandling: "greedy"
        });
    };

    window.radioOutdoorsWrappedBounds = function (positions) {
        const bounds = new google.maps.LatLngBounds();
        if (!positions.length) return bounds;
        const longitudes = positions.map(function (position) {
            return Number(position.lng);
        }).sort(function (a, b) { return a - b; });
        let largestGap = -1;
        let gapIndex = 0;
        longitudes.forEach(function (longitude, index) {
            const next = index === longitudes.length - 1
                ? longitudes[0] + 360
                : longitudes[index + 1];
            if (next - longitude > largestGap) {
                largestGap = next - longitude;
                gapIndex = index;
            }
        });
        const west = longitudes[(gapIndex + 1) % longitudes.length];
        positions.forEach(function (position) {
            let longitude = Number(position.lng);
            if (longitude < west) longitude += 360;
            bounds.extend(new google.maps.LatLng(Number(position.lat), longitude, true));
        });
        return bounds;
    };

    window.radioOutdoorsFitMap = function (map, positions, padding, maximumZoom) {
        if (!positions.length) return;
        if (positions.length === 1) {
            map.setCenter(positions[0]);
            map.setZoom(maximumZoom);
            return;
        }
        map.fitBounds(window.radioOutdoorsWrappedBounds(positions), padding);
        google.maps.event.addListenerOnce(map, "idle", function () {
            if (map.getZoom() > maximumZoom) map.setZoom(maximumZoom);
        });
    };
})();
