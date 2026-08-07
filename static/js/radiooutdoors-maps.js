(function () {
    "use strict";

    window.radioOutdoorsMapOptions = function (options) {
        return Object.assign({}, options, {
            gestureHandling: "greedy"
        });
    };
})();
