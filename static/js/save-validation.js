(function () {
    "use strict";
    const requiredMessage = "Save was not completed because required information is missing. Please complete the highlighted fields.";
    const generalMessage = "Save was not completed. Please correct the highlighted information.";
    let summarySequence = 0;

    function addDescription(field, id) {
        const ids = (field.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean);
        if (!ids.includes(id)) ids.push(id);
        field.setAttribute("aria-describedby", ids.join(" "));
    }
    function showBrowserSummary(form, field) {
        let summary = form.querySelector("[data-save-error-summary]");
        if (!summary) {
            summary = document.createElement("section");
            summary.id = `save-error-summary-${form.id || "form"}-${++summarySequence}`;
            summary.className = "form-error-summary save-error-summary";
            summary.setAttribute("role", "alert");
            summary.setAttribute("aria-live", "assertive");
            summary.setAttribute("tabindex", "-1");
            summary.dataset.saveErrorSummary = "";
            form.prepend(summary);
        }
        summary.replaceChildren();
        const heading = document.createElement("h2");
        heading.textContent = field.validity.valueMissing ? requiredMessage : generalMessage;
        summary.appendChild(heading);
        field.setAttribute("aria-invalid", "true");
        if (field.id) addDescription(field, summary.id);
        ensureInlineError(field, field.validationMessage || "This field is required.");
        window.setTimeout(() => summary.focus(), 0);
    }
    function ensureInlineError(field, message) {
        if (!field.id) return;
        const errorId = `${field.id}-save-error`;
        let error = document.getElementById(errorId);
        if (!error) {
            error = document.createElement("p");
            error.id = errorId;
            error.className = "form-error save-inline-error";
            error.dataset.saveInlineError = "";
            field.insertAdjacentElement("afterend", error);
        }
        error.textContent = message;
        addDescription(field, errorId);
    }
    document.addEventListener("DOMContentLoaded", () => {
        const summary = document.querySelector("[data-save-error-summary]");
        if (summary) {
            summary.querySelectorAll('a[href^="#"]').forEach(link => {
                const field = document.getElementById(link.getAttribute("href").slice(1));
                if (field) ensureInlineError(field, link.textContent.split(":").slice(1).join(":").trim());
            });
            summary.focus();
        }
    });
    document.addEventListener("invalid", event => {
        const field = event.target;
        if (field.form) showBrowserSummary(field.form, field);
    }, true);
    document.addEventListener("input", event => {
        if (event.target.validity && event.target.validity.valid) {
            event.target.removeAttribute("aria-invalid");
            const error = event.target.id && document.getElementById(`${event.target.id}-save-error`);
            if (error) error.remove();
        }
    });
})();
