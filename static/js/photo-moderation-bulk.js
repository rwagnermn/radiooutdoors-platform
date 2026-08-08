(function () {
  "use strict";
  var toolbar = document.querySelector("[data-photo-bulk-toolbar]");
  if (toolbar) {
    var boxes = Array.prototype.slice.call(document.querySelectorAll("[data-photo-select]"));
    var pageBox = document.querySelector("[data-select-page]");
    var count = toolbar.querySelector("[data-selection-count]");
    var action = toolbar.querySelector("[data-bulk-action]");
    function update() {
      var selected = boxes.filter(function (box) { return box.checked; }).length;
      count.textContent = selected + " selected";
      pageBox.checked = boxes.length > 0 && selected === boxes.length;
      pageBox.indeterminate = selected > 0 && selected < boxes.length;
    }
    pageBox.addEventListener("change", function () { boxes.forEach(function (box) { box.checked = pageBox.checked; }); update(); });
    boxes.forEach(function (box) { box.addEventListener("change", update); });
    toolbar.querySelector("[data-bulk-apply]").addEventListener("click", function (event) {
      if (action.value === "clear") { event.preventDefault(); boxes.forEach(function (box) { box.checked = false; }); action.value = ""; update(); }
    });
    update();
  }
  var grid = document.querySelector("[data-confirm-grid]");
  var confirmForm = document.querySelector("[data-bulk-confirm-form]");
  if (grid && confirmForm) {
    function selectedCards() { return Array.prototype.slice.call(grid.querySelectorAll("[data-confirm-select]")).filter(function (box) { return box.checked; }); }
    function refreshConfirm() {
      var number = selectedCards().length;
      var kind = confirmForm.dataset.actionKind;
      document.querySelector("[data-batch-heading] strong").textContent = kind === "approve" ? "Approve " + number + " selected photos? These photos will become publicly visible." : "Reject " + number + " selected photos?";
      confirmForm.querySelector("[data-confirm-button]").disabled = number === 0;
    }
    grid.querySelectorAll("[data-remove-from-batch]").forEach(function (button) { button.addEventListener("click", function () { var card = button.closest("[data-confirm-card]"); card.querySelector("[data-confirm-select]").checked = false; card.hidden = true; refreshConfirm(); }); });
    grid.querySelectorAll("[data-confirm-select]").forEach(function (box) { box.addEventListener("change", refreshConfirm); });
    confirmForm.addEventListener("submit", function (event) { var number = selectedCards().length; var message = confirmForm.dataset.actionKind === "approve" ? "Approve " + number + " selected photos? These photos will become publicly visible." : "Reject " + number + " selected photos?"; if (!window.confirm(message)) event.preventDefault(); });
    refreshConfirm();
  }
  document.querySelectorAll("[data-rejection-reason]").forEach(function (select) { var wrapper = select.closest("form"); var other = wrapper.querySelector("[data-other-reason]"); var explanation = other.querySelector("textarea"); function toggle() { var needed = select.value === "other"; other.hidden = !needed; explanation.required = needed; } select.addEventListener("change", toggle); toggle(); });
}());
