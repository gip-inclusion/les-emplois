"use strict";

// Dropdown span from the start of the city field to the end of the keyword field.
function alignServiceSearchDropdown(select) {
  const form = $(select.form);
  const ownContainer = $(select).data("select2").$container[0];
  const cityContainer = form.find("[data-service-search-city]").data("select2").$container[0];
  const keywordContainer = form.find("#id_services_keyword")[0];
  const dropdown = $(select).data("select2").$dropdown.find(".select2-dropdown")[0];
  const left = cityContainer.getBoundingClientRect().left;
  dropdown.style.marginLeft = `${left - ownContainer.getBoundingClientRect().left}px`;
  dropdown.style.minWidth = `${keywordContainer.getBoundingClientRect().right - left}px`;
}

const serviceSearchSelects = "[data-service-search-city]";
$(document).on("select2:open", serviceSearchSelects, function () {
  alignServiceSearchDropdown(this);
  $(window).on("resize.serviceSearchDropdown", () => alignServiceSearchDropdown(this));
});
$(document).on("select2:close", serviceSearchSelects, function () {
  $(window).off("resize.serviceSearchDropdown");
});
