(function () {
  "use strict";
  const form = document.getElementById("pota-import-form");
  if (!form) return;
  const button = document.getElementById("pota-review-button");
  const status = document.getElementById("pota-review-status");
  const reset = function () {
    button.disabled = false;
    button.textContent = "Review Activations";
    status.hidden = true;
  };
  form.addEventListener("submit", function () {
    button.disabled = true;
    button.textContent = "Reviewing Activations…";
    status.hidden = false;
  });
  window.addEventListener("pageshow", reset);
  const error = document.getElementById("pota-import-error");
  if (error) {
    error.focus();
    error.scrollIntoView({ block: "start" });
    const dismiss = error.querySelector(".pota-error-dismiss");
    if (dismiss) dismiss.addEventListener("click", function () { error.remove(); });
    const textarea = document.getElementById("pota-history");
    if (textarea) textarea.addEventListener("input", function () { if (error.isConnected) error.remove(); }, { once: true });
  }
}());
