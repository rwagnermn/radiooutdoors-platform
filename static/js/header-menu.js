(function () {
    "use strict";

    const menus = document.querySelectorAll(
        "details.account-menu, details.ro-action-menu"
    );

    menus.forEach(function (menu) {
        const summary = menu.querySelector("summary");
        const panel = menu.querySelector(
            ".account-menu-panel, .ro-action-menu-panel"
        );

        function closeMenu(returnFocus) {
            menu.open = false;
            summary.setAttribute("aria-expanded", "false");
            panel.style.removeProperty("position");
            panel.style.removeProperty("top");
            panel.style.removeProperty("left");
            panel.style.removeProperty("right");
            if (returnFocus) {
                summary.focus();
            }
        }

        function positionRowMenu() {
            if (!menu.classList.contains("adventure-row-menu") || !menu.open) return;

            const trigger = summary.getBoundingClientRect();
            const panelRect = panel.getBoundingClientRect();
            const gap = 8;
            const left = Math.max(
                gap,
                Math.min(trigger.right - panelRect.width, window.innerWidth - panelRect.width - gap)
            );
            const below = trigger.bottom + gap;
            const top = below + panelRect.height <= window.innerHeight - gap
                ? below
                : Math.max(gap, trigger.top - panelRect.height - gap);

            panel.style.position = "fixed";
            panel.style.left = left + "px";
            panel.style.top = top + "px";
            panel.style.right = "auto";
        }

        menu.addEventListener("toggle", function () {
            summary.setAttribute("aria-expanded", menu.open ? "true" : "false");
            if (menu.open) window.requestAnimationFrame(positionRowMenu);
        });

        panel.addEventListener("click", function (event) {
            if (event.target.closest("a, button")) {
                closeMenu(false);
            }
        });

        menu.addEventListener("keydown", function (event) {
            if (event.key === "Escape" && menu.open) {
                event.preventDefault();
                closeMenu(true);
            }
        });
    });

    document.addEventListener("click", function (event) {
        menus.forEach(function (menu) {
            if (menu.open && !menu.contains(event.target)) {
                menu.open = false;
                menu.querySelector("summary").setAttribute("aria-expanded", "false");
            }
        });
    });

    window.addEventListener("resize", function () {
        menus.forEach(function (menu) {
            if (menu.open) menu.querySelector("summary").click();
        });
    });
}());
