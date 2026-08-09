(function () {
    "use strict";

    function focusableElements(dialog) {
        return Array.from(dialog.querySelectorAll(
            'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )).filter(function (element) {
            return !element.hidden && element.getAttribute("aria-hidden") !== "true";
        });
    }

    document.querySelectorAll("[data-policy-acceptance]").forEach(function (fieldset) {
        var trigger = fieldset.querySelector("[data-policy-review-open]");
        var status = fieldset.querySelector("[data-policy-review-status]");
        var checkbox = fieldset.querySelector('input[name="policy_accepted"]');
        var dialog = document.getElementById(trigger && trigger.getAttribute("aria-controls"));
        if (!trigger || !dialog || !checkbox) return;

        function closeDialog(accepted) {
            if (accepted) {
                checkbox.checked = true;
                checkbox.dispatchEvent(new Event("input", { bubbles: true }));
                checkbox.dispatchEvent(new Event("change", { bubbles: true }));
                status.textContent = "Required policies accepted. Complete the age confirmation and submit your registration.";
                status.hidden = false;
            }
            dialog.hidden = true;
            document.body.classList.remove("policy-dialog-open");
            trigger.focus();
        }

        function openDialog() {
            dialog.hidden = false;
            document.body.classList.add("policy-dialog-open");
            var closeButton = dialog.querySelector("[data-policy-review-close]");
            window.requestAnimationFrame(function () { closeButton.focus(); });
        }

        trigger.addEventListener("click", openDialog);
        dialog.querySelectorAll("[data-policy-review-close]").forEach(function (button) {
            button.addEventListener("click", function () { closeDialog(false); });
        });
        dialog.querySelector("[data-policy-review-accept]").addEventListener("click", function () {
            closeDialog(true);
        });
        dialog.addEventListener("click", function (event) {
            if (event.target === dialog) closeDialog(false);
        });
        dialog.addEventListener("keydown", function (event) {
            if (event.key === "Escape") {
                event.preventDefault();
                closeDialog(false);
                return;
            }
            if (event.key !== "Tab") return;
            var elements = focusableElements(dialog);
            if (!elements.length) return;
            var first = elements[0];
            var last = elements[elements.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        });
    });
}());
