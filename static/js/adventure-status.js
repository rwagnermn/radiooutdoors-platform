(function () {
    "use strict";

    document.addEventListener("click", function (event) {
        if (event.target.closest("[data-adventure-status-form]")) {
            event.stopPropagation();
        }
    }, true);

    document.addEventListener("keydown", function (event) {
        if (event.target.closest("[data-adventure-status-form]")) {
            event.stopPropagation();
        }
    }, true);

    document.addEventListener("submit", async function (event) {
        const form = event.target.closest("[data-adventure-status-form]");
        if (!form) return;

        event.preventDefault();
        event.stopPropagation();

        const button = form.querySelector("[data-adventure-status-control]");
        const oldLabel = button.textContent.trim();
        const oldAction = form.action;
        const oldClass = oldLabel === "Open" ? "open" : "complete";
        const nextLabel = oldLabel === "Open" ? "Complete" : "Open";
        const nextClass = nextLabel.toLowerCase();

        button.disabled = true;
        button.textContent = nextLabel;
        button.classList.remove("adventure-status-" + oldClass);
        button.classList.add("adventure-status-" + nextClass);

        try {
            const response = await fetch(form.action, {
                method: "POST",
                body: new FormData(form),
                credentials: "same-origin",
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json"
                }
            });

            if (!response.ok) throw new Error("The status could not be saved.");

            const data = await response.json();
            button.textContent = data.label;
            button.classList.remove("adventure-status-open", "adventure-status-complete");
            button.classList.add("adventure-status-" + data.key);
            form.action = data.toggle_url;
        } catch (error) {
            button.textContent = oldLabel;
            button.classList.remove("adventure-status-open", "adventure-status-complete");
            button.classList.add("adventure-status-" + oldClass);
            form.action = oldAction;
            window.alert(error.message || "The status could not be saved. Please try again.");
        } finally {
            button.disabled = false;
        }
    });
}());
