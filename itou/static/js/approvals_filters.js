function submitFiltersForm() {
  $("#js-job-applications-filters-form").submit();
}
$("#js-job-applications-filters-form :input").change(submitFiltersForm);
$("#js-job-applications-filters-apply-button").hide();
