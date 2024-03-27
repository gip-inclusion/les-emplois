"use strict";

(function () {
  htmx.on("htmx:beforeRequest", (e) => {
    const triggerElt = e.target;
    const swapElt = triggerElt.closest("[hx-swap]");
    const swapMode = swapElt && swapElt.getAttribute("hx-swap") || htmx.config.defaultSwapStyle;
    if (swapMode === "outerHTML") {
      let loadingElt = triggerElt.closest("[hx-indicator]");
      let loadingIndicator = loadingElt && loadingElt.getAttribute("hx-indicator");
      loadingIndicator = loadingIndicator
        ? document.querySelector(loadingIndicator)
        : triggerElt;
      loadingIndicator.setAttribute("role", "status");
      // New DOM cleans the role when swapped in.
    } else {
      console.warn(
        `Swap mode “${swapMode}” is not implemented, ` +
        'add a “role="status"” to the element showing loading indicator.'
      );
    }
  });

  htmx.on("htmx:afterOnLoad", (e) => {
    const responseStatus = e.detail.xhr.status;
    if (200 <= responseStatus && responseStatus < 300) {
      initDuetDatePicker();
    }
  });

  htmx.on("htmx:responseError", (e) => {
    alert(`Erreur code ${e.detail.xhr.status} (${e.detail.xhr.statusText})\n\n`);
  });

  htmx.on("htmx:sendError", () => {
    alert("Erreur de connexion\nVeuillez vérifier votre connexion internet et réessayer plus tard.");
  });
})();
