"use strict";

(function () {
  htmx.on("htmx:afterOnLoad", (e) => {
    const responseStatus = e.detail.xhr.status;
    if (200 <= responseStatus && responseStatus < 300) {
      initDuetDatePicker();
      // - We're looking for the modal that is supposedly referred by the `htmx-open-modal` data element on the form.
      // - This form is either using `hx-swap=innerHtml` in which case it is `e.detail.elt`
      // - or it uses `outerHtml`, in which case we have to traverse `e.detail.elt` to find our form back.
      var element = $(e.detail.elt).find("*[data-htmx-open-modal]")[0] || $(e.detail.elt)[0];
      if (typeof element !== "undefined") {
        var modal_selector = element.dataset.htmxOpenModal;
        $(modal_selector).modal("show");
      }
    }
  });

  htmx.on("htmx:responseError", (e) => {
    alert(`Erreur code ${e.detail.xhr.status} (${e.detail.xhr.statusText})\n\n`);
  });

  htmx.on("htmx:sendError", () => {
    alert("Erreur de connexion\nVeuillez vérifier votre connexion internet et réessayer plus tard.");
  });
})();
