(function () {
    "use strict";
    const firstMissingAcceptance = document.querySelector(
        "[data-policy-acceptance] input[data-policy-required]:invalid"
    );
    const summary = document.getElementById("registration-error-summary");
    if (firstMissingAcceptance) firstMissingAcceptance.focus();
    else if (summary) summary.focus();
})();
