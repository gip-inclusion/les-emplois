// Only for <ul.s-tabs-01__nav.nav.nav-tabs> how has data-it-sliding-tabs="true" attribute
let slidingTabs = document.querySelector("[data-it-sliding-tabs=true]");

if (slidingTabs) {
  let slidingTabsStartIndex = 0;

  if (slidingTabs.hasAttribute("data-it-sliding-tabs-startindex")) {
    slidingTabsStartIndex = slidingTabs.getAttribute("data-it-sliding-tabs-startindex")
  }

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
    controls: false,
    startIndex: slidingTabsStartIndex,
  });
}
