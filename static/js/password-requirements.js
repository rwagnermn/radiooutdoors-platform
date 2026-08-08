(function () {
    "use strict";

    function csrfToken(form) {
        const field = form.querySelector('input[name="csrfmiddlewaretoken"]');
        return field ? field.value : "";
    }

    function identityValue(checklist, form, name, selectors) {
        const configured = checklist.dataset[name];
        if (configured) return configured;
        for (const selector of selectors) {
            const field = form.querySelector(selector);
            if (field && field.value) return field.value;
        }
        return "";
    }

    function update(checklist, statuses) {
        checklist.querySelectorAll("[data-requirement]").forEach(function (item) {
            const satisfied = statuses[item.dataset.requirement] === true;
            item.dataset.satisfied = satisfied ? "true" : "false";
            const state = item.querySelector(".password-requirement-state");
            state.textContent = satisfied ? "Satisfied:" : "Still needed:";
        });
    }

    document.querySelectorAll("[data-password-requirements]").forEach(function (checklist) {
        const form = checklist.closest("form");
        if (!form) return;
        const password = form.querySelector("#id_password1, #id_new_password1");
        if (!password) return;

        let timer;
        let controller;
        function validate() {
            window.clearTimeout(timer);
            timer = window.setTimeout(function () {
                if (controller) controller.abort();
                controller = new AbortController();
                const body = new URLSearchParams({
                    password: password.value,
                    username: identityValue(checklist, form, "username", ["#id_callsign", "#id_username"]),
                    email: identityValue(checklist, form, "email", ["#id_email"]),
                    first_name: identityValue(checklist, form, "firstName", ["#id_first_name"]),
                    last_name: identityValue(checklist, form, "lastName", ["#id_last_name"]),
                });
                fetch(checklist.dataset.endpoint, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                        "X-CSRFToken": csrfToken(form),
                    },
                    body: body.toString(),
                    credentials: "same-origin",
                    signal: controller.signal,
                })
                    .then(function (response) {
                        if (!response.ok) throw new Error("Password validation unavailable");
                        return response.json();
                    })
                    .then(function (data) { update(checklist, data.requirements || {}); })
                    .catch(function (error) {
                        if (error.name !== "AbortError") update(checklist, {});
                    });
            }, 250);
        }

        password.addEventListener("input", validate);
        form.querySelectorAll("#id_callsign, #id_email, #id_first_name, #id_last_name").forEach(function (field) {
            field.addEventListener("input", validate);
        });
    });
})();
