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
            if (returnFocus) {
                summary.focus();
            }
        }

        menu.addEventListener("toggle", function () {
            summary.setAttribute("aria-expanded", menu.open ? "true" : "false");
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
}());
