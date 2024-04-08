"use strict";

(function() {
  function initSlider() {
    const slider = document.getElementById("chosenPercentRange");
    const output = document.getElementById("showChosenPercentValue");
    output.textContent = slider.value;

    slider.oninput = function () {
      output.textContent = this.value;
    }
  }

  function initConfirmModal() {
    document.getElementById("ratio-form").addEventListener("submit", function (e) {
      const text = "Le ratio sélectionné ne sera plus modifiable pour cette campagne de contrôle. Confirmez-vous son enregistrement ?";
      if (!window.confirm(text)) {
        e.preventDefault();
      } else {
        // Clicking cancel in the window.confirm should not lock the submit
        // button.
        e.submitter.disabled = true;
      }
    })
  }

  initSlider();
  initConfirmModal();
})()
