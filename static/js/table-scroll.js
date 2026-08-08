(function () {
    "use strict";

    document.addEventListener("keydown", function (event) {
        const region = event.target.closest(".ro-scroll-table-region");
        if (!region || event.target !== region || region.scrollHeight <= region.clientHeight) return;

        const pageStep = Math.max(120, region.clientHeight * 0.85);
        const scrollByKey = {
            ArrowDown: 48,
            ArrowUp: -48,
            PageDown: pageStep,
            PageUp: -pageStep
        };

        if (event.key in scrollByKey) {
            event.preventDefault();
            region.scrollBy({ top: scrollByKey[event.key] });
        } else if (event.key === "Home") {
            event.preventDefault();
            region.scrollTo({ top: 0 });
        } else if (event.key === "End") {
            event.preventDefault();
            region.scrollTo({ top: region.scrollHeight });
        }
    });
}());
