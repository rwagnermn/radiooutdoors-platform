(function () {
    "use strict";
    document.querySelectorAll("[data-set-amenities]").forEach(function (button) {
        button.addEventListener("click", function () {
            const heading = button.closest(".amenities-editor-heading");
            const editor = heading && heading.nextElementSibling;
            if (!editor || !editor.matches("[data-amenities-editor]")) return;
            editor.querySelectorAll("select").forEach(function (select) {
                if (Array.from(select.options).some(function (option) { return option.value === button.dataset.setAmenities; })) {
                    select.value = button.dataset.setAmenities;
                    select.dispatchEvent(new Event("change", {bubbles: true}));
                }
            });
        });
    });
}());
