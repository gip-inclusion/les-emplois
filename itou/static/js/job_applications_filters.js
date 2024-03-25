function submitFiltersForm() {
    $("#js-job-applications-filters-form").submit();
}
$("#js-job-applications-filters-form :input").change(submitFiltersForm);
$("duet-date-picker").on("duetChange", submitFiltersForm);
$("#js-job-applications-filters-apply-button").hide();
