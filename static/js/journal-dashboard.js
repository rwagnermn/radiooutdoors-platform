(function () {
    "use strict";

    const strip = document.querySelector("[data-journal-photo-carousel]");
    if (!strip) return;
    const previous = document.querySelector("[data-journal-carousel-prev]");
    const next = document.querySelector("[data-journal-carousel-next]");
    const updateArrows = function () {
        previous.disabled = strip.scrollLeft <= 1;
        next.disabled = strip.scrollLeft + strip.clientWidth >= strip.scrollWidth - 1;
    };
    const move = function (direction) {
        const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        strip.scrollBy({left: direction * Math.max(240, strip.clientWidth * .72), behavior: reducedMotion ? "auto" : "smooth"});
    };
    previous.addEventListener("click", function () { move(-1); });
    next.addEventListener("click", function () { move(1); });
    strip.addEventListener("scroll", updateArrows, {passive: true});
    strip.addEventListener("keydown", function (event) {
        if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
            event.preventDefault();
            move(event.key === "ArrowLeft" ? -1 : 1);
        }
    });
    updateArrows();
    window.addEventListener("resize", updateArrows);
}());
