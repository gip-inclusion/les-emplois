// Show or Hide the search-filter-form sidebar based on responsive breakpoint
var breakpointMD = getComputedStyle(document.documentElement).getPropertyValue("--breakpoint-md");
$(window).on("load resize", function() {
    if (window.matchMedia("(min-width: "+breakpointMD+")").matches) {
        $("job-aside-filters-form").collapse("show");
    } else {
        $("job-aside-filters-form").collapse("hide");
    }
});
