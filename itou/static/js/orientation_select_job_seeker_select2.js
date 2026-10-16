"use strict";

function noJobSeekerResults() {
  const createJobSeekerUrl = $("#id_job_seeker").closest("form").data("create-job-seeker-url");

  return $("<span>").append(
    "Aucun résultat trouvé. ",
    $("<a>", {
      href: createJobSeekerUrl,
      class: "btn-link",
      text: "Créer un compte usager",
    })
  );
}

function customizeJobSeekerSelect2() {
  const jobSeekerSelect = $("#id_job_seeker");
  const select2 = jobSeekerSelect.data("select2");
  if (!select2) {
    return;
  }
  select2.options.get("translations").dict.noResults = noJobSeekerResults;
}

window.addEventListener("load", customizeJobSeekerSelect2, { once: true });
