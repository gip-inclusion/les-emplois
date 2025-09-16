"use strict";

htmx.onLoad(function(target) {
  target.querySelectorAll("[data-it-sliding-search=true]").forEach(function (slidingSearch) {
    tns({
      container: slidingSearch,
      slideBy: "page",
      autoWidth: true,
      arrowKeys: false,
      loop: false,
      mouseDrag: false,
      swipeAngle: false,
      speed: 300,
      gutter: 12,
      nav: false,
      controls: true,
      startIndex: 0,
    });
  })
});
