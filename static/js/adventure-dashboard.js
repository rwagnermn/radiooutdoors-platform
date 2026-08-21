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

(function () {
    "use strict";
    document.querySelectorAll("[data-scroll-shell]").forEach(function (shell) {
        const viewport = shell.querySelector("[data-scroll-viewport]");
        const up = shell.querySelector("[data-scroll-up]");
        const down = shell.querySelector("[data-scroll-down]");
        const thumb = shell.querySelector("[data-scroll-thumb]");
        if (!viewport || !up || !down || !thumb) return;

        let syncing = false;
        const update = function () {
            const maximum = Math.max(0, viewport.scrollHeight - viewport.clientHeight);
            const position = maximum ? Math.round((viewport.scrollTop / maximum) * 100) : 0;
            syncing = true;
            thumb.value = String(position);
            syncing = false;
            up.disabled = viewport.scrollTop <= 1;
            down.disabled = viewport.scrollTop >= maximum - 1;
            thumb.disabled = maximum === 0;
        };
        const move = function (direction) {
            viewport.scrollBy({
                top: direction * Math.max(56, Math.round(viewport.clientHeight * 0.65)),
                behavior: "smooth",
            });
        };

        up.addEventListener("click", function () { move(-1); });
        down.addEventListener("click", function () { move(1); });
        thumb.addEventListener("input", function () {
            if (syncing) return;
            const maximum = Math.max(0, viewport.scrollHeight - viewport.clientHeight);
            viewport.scrollTop = maximum * (Number(thumb.value) / 100);
        });
        viewport.addEventListener("scroll", update, { passive: true });
        window.addEventListener("resize", update);
        update();
    });
}());

(function () {
    "use strict";
    document.querySelectorAll("[data-journal-url]").forEach(function (row) {
        row.addEventListener("click", function (event) {
            if (event.defaultPrevented || event.button !== 0) return;
            if (event.target.closest("a, button, input, select, textarea, summary, details, form")) return;
            const selection = window.getSelection();
            if (selection && !selection.isCollapsed) return;
            window.location.assign(row.dataset.journalUrl);
        });
    });
}());

(function () {
    "use strict";
    document.querySelectorAll("[data-photo-carousel]").forEach(function (carousel) {
        const track = carousel.querySelector("[data-carousel-track]");
        const previous = carousel.querySelector("[data-carousel-previous]");
        const next = carousel.querySelector("[data-carousel-next]");
        if (!track || !previous || !next) return;

        const update = function () {
            const maximum = Math.max(0, track.scrollWidth - track.clientWidth);
            previous.disabled = track.scrollLeft <= 1;
            next.disabled = track.scrollLeft >= maximum - 1;
        };
        const move = function (direction) {
            track.scrollBy({ left: direction * track.clientWidth, behavior: "smooth" });
        };

        previous.addEventListener("click", function () { move(-1); });
        next.addEventListener("click", function () { move(1); });
        track.addEventListener("scroll", update, { passive: true });
        window.addEventListener("resize", update);
        update();
    });
}());

(function () {
    "use strict";
    const notice = document.querySelector("[data-journal-storage-notice]");
    if (!notice) return;
    window.setTimeout(function () {
        notice.classList.add("is-permanent");
    }, 3000);
}());
