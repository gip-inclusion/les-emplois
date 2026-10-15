"use strict";

$.fn.select2.defaults.set("dropdownCssClass", ($element) =>
  $element.is("[data-service-search-category]") ? "c-search-dropdown" : ""
);
