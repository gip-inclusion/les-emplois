"use strict";

$.fn.select2.defaults.set("dropdownCssClass", ($element) =>
  $element.is("[data-service-search-category]") ? "c-search-dropdown" : ""
);

// On the home page, both dropdowns span from the start of the city field to the end of the category field.
function alignServiceSearchDropdown(select) {
  const form = $(select.form);
  const ownContainer = $(select).data("select2").$container[0];
  const cityContainer = form.find("[data-service-search-city]").data("select2").$container[0];
  const categoryContainer = form.find("[data-service-search-category]").data("select2").$container[0];
  const dropdown = $(select).data("select2").$dropdown.find(".select2-dropdown")[0];
  const left = cityContainer.getBoundingClientRect().left;
  dropdown.style.marginLeft = `${left - ownContainer.getBoundingClientRect().left}px`;
  dropdown.style.minWidth = `${categoryContainer.getBoundingClientRect().right - left}px`;
}

const serviceSearchSelects =
  ".s-home-search [data-service-search-city], .s-home-search [data-service-search-category]";
$(document).on("select2:open", serviceSearchSelects, function () {
  alignServiceSearchDropdown(this);
  $(window).on("resize.serviceSearchDropdown", () => alignServiceSearchDropdown(this));
});
$(document).on("select2:close", serviceSearchSelects, function () {
  $(window).off("resize.serviceSearchDropdown");
});
