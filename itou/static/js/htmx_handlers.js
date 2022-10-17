"use strict";

(function () {
  htmx.on("htmx:afterOnLoad", (e) => {
    const responseStatus = e.detail.xhr.status;
    if (200 <= responseStatus && responseStatus < 300) {
      $(e.detail.elt.dataset.htmxOpenModal).modal("show");
    }
  });

  htmx.on("htmx:responseError", (e) => {
    alert(`Erreur code ${e.detail.xhr.status} (${e.detail.xhr.statusText})\n\n`);
  });

  htmx.on("htmx:sendError", () => {
    alert("Erreur de connexion\nVeuillez vérifier votre connexion internet et réessayer plus tard.");
  });
})();
