(function () {
    "use strict";

    const form = document.querySelector("[data-journal-bulk-selection]");
    if (!form) return;

    const action = form.querySelector("[data-journal-selection-action]");
    const checkboxes = Array.from(form.querySelectorAll("[data-journal-selector]"));
    const selectedInput = form.querySelector("[data-selected-journal-ids]");
    const selectedCount = form.querySelector("[data-journal-selection-count]");
    const errorMessage = form.querySelector("[data-journal-selection-error]");
    const deleteButton = form.querySelector("[data-delete-selected-journals]");
    const customControl = form.querySelector("[data-random-number-control]");
    const customInput = form.querySelector("[data-random-number-input]");
    const customApply = form.querySelector("[data-apply-random-number]");
    const eligibleCount = Number(form.dataset.eligibleCount || 0);
    let selected = new Set();

    function showError(message) {
        errorMessage.textContent = message || "";
        errorMessage.hidden = !message;
    }

    function renderSelection() {
        checkboxes.forEach(function (checkbox) {
            checkbox.checked = selected.has(Number(checkbox.value));
        });
        const selectedIds = Array.from(selected);
        selectedInput.value = JSON.stringify(selectedIds);
        selectedCount.textContent = selectedIds.length + " of " + eligibleCount + " Journals selected";
        deleteButton.disabled = selectedIds.length === 0;
    }

    async function replaceSelection(mode, count) {
        showError("");
        const url = new URL(form.dataset.selectionUrl, window.location.origin);
        url.searchParams.set("mode", mode);
        if (count !== undefined) url.searchParams.set("count", String(count));
        url.searchParams.set("_", String(Date.now()));
        const response = await fetch(url.toString(), {
            credentials: "same-origin",
            headers: {"X-Requested-With": "XMLHttpRequest"}
        });
        const payload = await response.json();
        if (!response.ok) {
            showError(payload.error || "The Journal selection could not be completed.");
            return;
        }
        selected = new Set(payload.journal_ids.map(Number));
        renderSelection();
    }

    action.addEventListener("change", function () {
        customControl.hidden = action.value !== "custom";
        if (!action.value || action.value === "custom") {
            if (action.value === "custom") customInput.focus();
            return;
        }
        if (action.value.indexOf("random:") === 0) {
            replaceSelection("random", Number(action.value.split(":")[1])).catch(function () {
                showError("The Journal selection could not be completed.");
            });
        } else {
            replaceSelection(action.value).catch(function () {
                showError("The Journal selection could not be completed.");
            });
        }
    });

    customApply.addEventListener("click", function () {
        const rawValue = customInput.value.trim();
        const count = Number(rawValue);
        if (!/^\d+$/.test(rawValue) || count < 1) {
            showError("Enter a whole number of Journals from 1 through " + eligibleCount + ".");
            return;
        }
        if (count > eligibleCount) {
            showError("Only " + eligibleCount + " Journals are eligible in this Adventure.");
            return;
        }
        replaceSelection("random", count).catch(function () {
            showError("The Journal selection could not be completed.");
        });
    });

    checkboxes.forEach(function (checkbox) {
        checkbox.addEventListener("change", function () {
            const journalId = Number(checkbox.value);
            if (checkbox.checked) selected.add(journalId);
            else selected.delete(journalId);
            showError("");
            renderSelection();
        });
    });

    form.addEventListener("submit", function (event) {
        renderSelection();
        if (!selected.size) {
            event.preventDefault();
            showError("Select at least one Journal before continuing to deletion confirmation.");
        }
    });

    renderSelection();
}());
