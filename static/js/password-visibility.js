(function () {
    "use strict";

    const showIcon = [
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">',
        '<path d="M2.3 12s3.5-6 9.7-6 9.7 6 9.7 6-3.5 6-9.7 6-9.7-6-9.7-6Z"/>',
        '<circle cx="12" cy="12" r="3"/>',
        "</svg>",
    ].join("");
    const hideIcon = [
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">',
        '<path d="M3 3l18 18"/>',
        '<path d="M10.6 6.1A10.8 10.8 0 0 1 12 6c6.2 0 9.7 6 9.7 6a17.5 17.5 0 0 1-3 3.7M6.2 6.2C3.6 8.1 2.3 12 2.3 12s3.5 6 9.7 6c1.3 0 2.5-.3 3.5-.7"/>',
        '<path d="M9.9 9.9A3 3 0 0 0 14.1 14.1"/>',
        "</svg>",
    ].join("");

    function enhance(input) {
        if (input.dataset.passwordVisibilityReady === "true") return;
        input.dataset.passwordVisibilityReady = "true";

        const wrapper = document.createElement("div");
        wrapper.className = "password-visibility-field";
        input.parentNode.insertBefore(wrapper, input);
        wrapper.appendChild(input);

        const button = document.createElement("button");
        button.type = "button";
        button.className = "password-visibility-toggle";
        button.setAttribute("aria-label", "Show password");
        button.setAttribute("title", "Show password");
        button.setAttribute("aria-pressed", "false");
        if (input.id) button.setAttribute("aria-controls", input.id);
        button.innerHTML = showIcon;

        button.addEventListener("click", function () {
            const showing = input.type === "text";
            input.type = showing ? "password" : "text";
            const action = showing ? "Show password" : "Hide password";
            button.setAttribute("aria-label", action);
            button.setAttribute("title", action);
            button.setAttribute("aria-pressed", showing ? "false" : "true");
            button.innerHTML = showing ? showIcon : hideIcon;
            input.focus({ preventScroll: true });
        });

        wrapper.appendChild(button);
    }

    function enhanceAll(root) {
        root.querySelectorAll('input[type="password"]').forEach(enhance);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () {
            enhanceAll(document);
        });
    } else {
        enhanceAll(document);
    }
})();
