(function () {
  "use strict";
  var toolbar = document.querySelector("[data-photo-bulk-toolbar]");
  if (toolbar) {
    var boxes = Array.prototype.slice.call(document.querySelectorAll("[data-photo-select]"));
    var pageBox = document.querySelector("[data-select-page]");
    var count = toolbar.querySelector("[data-selection-count]");
    var action = toolbar.querySelector("[data-bulk-action]");
    var error = document.querySelector("[data-bulk-selection-error]");
    var dismissError = error && error.querySelector("[data-dismiss-selection-error]");
    function hideSelectionError() { if (error) error.hidden = true; }
    function showSelectionError() {
      if (!error) return;
      error.hidden = false;
      error.focus();
    }
    function update() {
      var selected = boxes.filter(function (box) { return box.checked; }).length;
      count.textContent = selected + " selected";
      pageBox.checked = boxes.length > 0 && selected === boxes.length;
      pageBox.indeterminate = selected > 0 && selected < boxes.length;
      if (selected > 0) hideSelectionError();
    }
    pageBox.addEventListener("change", function () { boxes.forEach(function (box) { box.checked = pageBox.checked; }); update(); });
    boxes.forEach(function (box) { box.addEventListener("change", update); });
    toolbar.querySelector("[data-bulk-apply]").addEventListener("click", function (event) {
      if (action.value === "clear") { event.preventDefault(); boxes.forEach(function (box) { box.checked = false; }); action.value = ""; update(); }
      else if (!boxes.some(function (box) { return box.checked; })) { event.preventDefault(); showSelectionError(); }
    });
    if (dismissError) dismissError.addEventListener("click", hideSelectionError);
    update();
  }
  var grid = document.querySelector("[data-confirm-grid]");
  var confirmForm = document.querySelector("[data-bulk-confirm-form]");
  if (grid && confirmForm) {
    var submitting = false;
    function selectedCards() { return Array.prototype.slice.call(grid.querySelectorAll("[data-confirm-select]")).filter(function (box) { return box.checked; }); }
    function refreshConfirm() {
      var number = selectedCards().length;
      var kind = confirmForm.dataset.actionKind;
      var photoLabel = number === 1 ? " photo" : " photos";
      var heading = kind === "approve"
        ? "Approve " + number + " selected" + photoLabel + "? These photos will become publicly visible."
        : kind === "remove"
          ? "Remove " + number + " selected" + photoLabel + "?"
          : "Reject " + number + " selected" + photoLabel + "?";
      document.querySelector("[data-batch-heading] strong").textContent = heading;
      confirmForm.querySelector("[data-confirm-button]").disabled = number === 0;
    }
    grid.querySelectorAll("[data-remove-from-batch]").forEach(function (button) { button.addEventListener("click", function () { var card = button.closest("[data-confirm-card]"); card.querySelector("[data-confirm-select]").checked = false; card.hidden = true; refreshConfirm(); }); });
    grid.querySelectorAll("[data-confirm-select]").forEach(function (box) { box.addEventListener("change", refreshConfirm); });
    confirmForm.addEventListener("submit", function (event) {
      if (submitting || selectedCards().length === 0) {
        event.preventDefault();
        return;
      }
      submitting = true;
      var button = confirmForm.querySelector("[data-confirm-button]");
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
      button.textContent = confirmForm.dataset.actionKind === "approve"
        ? "Approving..."
        : confirmForm.dataset.actionKind === "remove"
          ? "Removing..."
          : "Rejecting...";
    });
    refreshConfirm();
  }
  document.querySelectorAll("[data-rejection-reason]").forEach(function (select) { var wrapper = select.closest("form"); var other = wrapper.querySelector("[data-other-reason]"); var explanation = other.querySelector("textarea"); function toggle() { var needed = select.value === "other"; other.hidden = !needed; explanation.required = needed; } select.addEventListener("change", toggle); toggle(); });
  document.querySelectorAll("[data-removal-reason]").forEach(function (select) { var wrapper = select.closest("form"); var other = wrapper.querySelector("[data-other-removal-reason]"); var explanation = other.querySelector("textarea"); function toggle() { var needed = select.value === "other"; other.hidden = !needed; explanation.required = needed; } select.addEventListener("change", toggle); toggle(); });
}());
