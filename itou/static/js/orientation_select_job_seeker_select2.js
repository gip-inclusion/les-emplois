"use strict";

function noJobSeekerResults() {
  const createJobSeekerUrl = $("#id_job_seeker").closest("form").data("create-job-seeker-url");

  return $("<span>").append(
    "Aucun résultat trouvé. ",
    $("<a>", {
      href: createJobSeekerUrl,
      class: "btn-link",
      text: "Créer un compte usager",
    }).on("click", () => {
      window._paq.push(["trackEvent", "compte-candidat", "clic", "creer-un-compte-candidat-orientation-select2"]);
    })
  );
}

// Patched when the dropdown opens, not on page load: the select2 instance may not exist yet
// by the time this script runs, and `window.load` waits for every subresource (Matomo included).
// select2 relays its events on the original <select> with a bubbling jQuery event, so a delegated
// handler catches them whatever initializes the widget, and after an htmx swap.
$(document).on("select2:opening", "#id_job_seeker", function() {
  const select2 = $(this).data("select2");
  if (select2) {
    select2.options.get("translations").dict.noResults = noJobSeekerResults;
  }
});
