(function () {
    "use strict";

    const triggers = document.querySelectorAll(".journal-photo-viewer-trigger");
    if (!triggers.length) {
        return;
    }

    const dialog = document.createElement("dialog");
    dialog.className = "journal-photo-viewer";
    dialog.setAttribute("aria-label", "Original journal photo");
    dialog.innerHTML = [
        '<div class="journal-photo-viewer-toolbar">',
        '<button type="button" class="journal-photo-viewer-close">',
        'Reduce Photo and Return to Journal',
        '</button>',
        '</div>',
        '<div class="journal-photo-viewer-canvas">',
        '<img alt="">',
        '</div>'
    ].join("");
    document.body.appendChild(dialog);

    const image = dialog.querySelector("img");
    const closeButton = dialog.querySelector(".journal-photo-viewer-close");
    let returnFocusTo = null;

    function closeViewer() {
        dialog.close();
    }

    triggers.forEach(function (trigger) {
        trigger.addEventListener("click", function (event) {
            event.stopPropagation();
            returnFocusTo = trigger;
            image.src = trigger.dataset.fullSrc;
            image.alt = trigger.dataset.fullAlt || "Journal photo";
            dialog.showModal();
            closeButton.focus();
        });
    });

    closeButton.addEventListener("click", closeViewer);

    dialog.addEventListener("click", function (event) {
        if (event.target === dialog) {
            closeViewer();
        }
    });

    dialog.addEventListener("close", function () {
        image.removeAttribute("src");
        if (returnFocusTo) {
            returnFocusTo.focus();
        }
    });
})();
