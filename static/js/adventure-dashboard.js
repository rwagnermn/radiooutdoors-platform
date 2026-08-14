(function () {
    "use strict";
    const clamp = document.querySelector("[data-summary-clamp]");
    if (!clamp) return;
    const text = clamp.querySelector("[data-summary-text]");
    const toggle = clamp.querySelector("[data-summary-toggle]");
    if (!text || !toggle) return;

    const update = function () {
        const expanded = clamp.classList.contains("is-expanded");
        if (!expanded && text.scrollHeight > text.clientHeight + 1) toggle.hidden = false;
    };
    toggle.addEventListener("click", function () {
        const expanded = clamp.classList.toggle("is-expanded");
        toggle.setAttribute("aria-expanded", String(expanded));
        toggle.textContent = expanded ? "Less" : "More";
    });
    update();
    window.addEventListener("resize", update);
}());
