/********************************************************************
  Host-side script for the plateforme-accueil iframe:

  1. sizes it to its content, and publishes back the band of it that is on
     screen, so the embedded page can place a modal where the visitor is
     looking.

    The iframe is sandboxed without allow-same-origin, so its document sits in
    an opaque origin that no concrete targetOrigin can match. Hence "*", which
    is safe here: the message only reaches this frame, and frame-src decides
    what may load in it. It carries no secret either way.

  2. receives analytics events from the iframe and forwards them to Matomo
     (when user has consented to tracking).
********************************************************************/
"use strict";

(function () {
  window._paq = window._paq || [];

  const frame = document.querySelector("iframe[data-plateforme-accueil]");
  // https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe#error_and_load_event_behavior
  let frameLoaded = false;
  let frameHeight = null;

  function publishViewport() {
    var rect = frame.getBoundingClientRect();
    var top = Math.max(0, -rect.top);
    const remainingHeight = rect.height - top;
    const height = Math.round(
      Math.max(0, Math.min(window.innerHeight, Math.round(remainingHeight))),
    );
    // Off screen, or unchanged: nothing worth posting.
    if (height === 0 || frameHeight === height) {
      return;
    }
    frameHeight = height;
    frame.contentWindow.postMessage(
      {
        source: "plateforme-accueil",
        type: "viewport",
        top: top,
        height: height,
      },
      "*",
    );
  }

  let scheduled = null;
  function schedule() {
    if (scheduled === null) {
      scheduled = window.requestAnimationFrame(function () {
        scheduled = null;
        publishViewport();
      });
    }
  }

  window.addEventListener("message", function (evt) {
    const data = evt.data;
    if (
      !data ||
      data.source !== "plateforme-accueil" ||
      frame.contentWindow !== evt.source
    ) {
      return;
    }
    switch (data.type) {
      case "analytics":
        window._paq.push([
          "trackEvent",
          data.matomoCategory,
          data.matomoAction,
          data.matomoName,
        ]);
        break;
      case "resize":
        frameLoaded = true;
        frame.style.height = data.height + "px";
        schedule();
        break;
    }
  });
  // The iframe must not load before the listener above is installed to
  // catch the first resize message.
  frame.src = frame.dataset.plateformeAccueil;

  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", schedule);
  window.addEventListener("load", schedule);

  setTimeout(function () {
    if (!frameLoaded) {
      document
        .getElementById("loading-error-fallback")
        .classList.remove("d-none");
      frame.classList.add("d-none");
      window._paq.push([
        "trackEvent",
        "iframe",
        "load-failure",
        "plateforme-accueil",
      ]);
    }
  }, 10000);
})();
