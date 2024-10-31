"use strict";

htmx.onLoad(function(target) {
  target.querySelectorAll("[data-it-sliding-tabs=true]").forEach(function(slidingTabs) {
    const slidingTabsStartIndex = Number.parseInt(slidingTabs.getAttribute("data-it-sliding-tabs-startindex")) || 0;
    tns({
      container: slidingTabs,
      slideBy: "page",
      autoWidth: true,
      arrowKeys: true,
      loop: false,
      mouseDrag: true,
      swipeAngle: false,
      speed: 300,
      nav: false,
      controls: true,
      startIndex: slidingTabsStartIndex,
    });
  })
});
