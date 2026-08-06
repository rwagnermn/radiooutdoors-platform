(function () {
    function closeMenus(exceptPanel) {
        document.querySelectorAll(
            ".action-menu-panel.open, .header-menu-panel.open, [data-menu-panel].open"
        ).forEach(function (panel) {
            if (panel !== exceptPanel) {
                panel.classList.remove("open");
            }
        });
    }

    function menuPanelFor(button) {
        const menu = button.closest(
            ".action-menu, .header-menu, [data-menu]"
        );

        if (!menu) {
            return null;
        }

        return menu.querySelector(
            ".action-menu-panel, .header-menu-panel, [data-menu-panel]"
        );
    }

    document.addEventListener("click", function (event) {
        const button = event.target.closest(
            ".action-menu-button, .header-menu-button, [data-menu-button]"
        );

        if (button) {
            event.preventDefault();
            event.stopPropagation();

            const panel = menuPanelFor(button);
            const shouldOpen = panel && !panel.classList.contains("open");

            closeMenus(panel);

            if (panel) {
                panel.classList.toggle("open", shouldOpen);
                button.setAttribute(
                    "aria-expanded",
                    shouldOpen ? "true" : "false"
                );
            }

            return;
        }

        if (!event.target.closest(
            ".action-menu-panel, .header-menu-panel, [data-menu-panel]"
        )) {
            closeMenus(null);
        }
    });

    window.setTimeout(function () {
        document.querySelectorAll(".flash-message").forEach(function (message) {
            message.classList.add("flash-message-hiding");

            window.setTimeout(function () {
                message.remove();
            }, 350);
        });
    }, 5000);

    const table = document.getElementById("journal-contact-table");
    const search = document.getElementById("contact-search");

    if (!table || !search) {
        return;
    }

    const selectAll = document.getElementById("select-all-contacts");
    const selectVisible = document.getElementById("select-visible-contacts");
    const clearSelection = document.getElementById("clear-contact-selection");
    const deleteButton = document.getElementById("delete-selected-contacts");

    function allBoxes() {
        return Array.from(
            table.querySelectorAll(".contact-row-checkbox")
        );
    }

    function visibleBoxes() {
        return allBoxes().filter(function (box) {
            return !box.closest("tr").hidden;
        });
    }

    function updateControls() {
        const selected = allBoxes().filter(function (box) {
            return box.checked;
        });

        if (deleteButton) {
            deleteButton.disabled = selected.length === 0;
            deleteButton.textContent = selected.length
                ? "Delete Selected (" + selected.length + ")"
                : "Delete Selected";
        }

        if (selectAll) {
            const visible = visibleBoxes();

            selectAll.checked =
                visible.length > 0 &&
                visible.every(function (box) {
                    return box.checked;
                });
        }
    }

    search.addEventListener("input", function () {
        const query = search.value.trim().toLowerCase();

        table.querySelectorAll("tbody tr").forEach(function (row) {
            row.hidden = Boolean(
                query &&
                !row.textContent.toLowerCase().includes(query)
            );
        });

        updateControls();
    });

    table.addEventListener("change", function (event) {
        if (event.target.classList.contains("contact-row-checkbox")) {
            updateControls();
        }
    });

    if (selectAll) {
        selectAll.addEventListener("change", function () {
            visibleBoxes().forEach(function (box) {
                box.checked = selectAll.checked;
            });

            updateControls();
        });
    }

    if (selectVisible) {
        selectVisible.addEventListener("click", function () {
            visibleBoxes().forEach(function (box) {
                box.checked = true;
            });

            updateControls();
        });
    }

    if (clearSelection) {
        clearSelection.addEventListener("click", function () {
            allBoxes().forEach(function (box) {
                box.checked = false;
            });

            updateControls();
        });
    }

    window.confirmContactDelete = function () {
        const count = allBoxes().filter(function (box) {
            return box.checked;
        }).length;

        if (!count) {
            return false;
        }

        return window.confirm(
            "Delete " + count + " selected contact" +
            (count === 1 ? "?" : "s?") +
            "\n\nThis cannot be undone."
        );
    };

    updateControls();
})();
