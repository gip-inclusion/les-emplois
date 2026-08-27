/********************************************************************
  Host-side script for the plateforme-accueil iframe: sizes it to its
  content, and publishes back the band of it that is on screen, so the
  embedded page can place a modal where the visitor is looking.

  Copied from plateforme-accueil, accueil/static/accueil/js/iframe-embed.js,
  rather than loaded from that origin: script-src is site-wide, so allowing
  that host would let it run scripts on every page. Keep in sync.

  The iframe is sandboxed without allow-same-origin, so its document sits in
  an opaque origin that no concrete targetOrigin can match. Hence "*", which
  is safe here: the message only reaches this frame, and frame-src decides
  what may load in it. It carries no secret either way.
********************************************************************/
"use strict";

(function() {
  function frames() {
    return document.querySelectorAll("iframe[data-plateforme-accueil]");
  }

  // The visible band, in the embedded document's coordinates. That document
  // does not scroll, so there is no second offset to reconcile.
  function publishViewport(frame) {
    if (!frame.contentWindow) {
      return;
    }
    const rect = frame.getBoundingClientRect();
    const top = Math.round(Math.max(0, -rect.top));
    const height = Math.round(Math.max(0, Math.min(rect.height, window.innerHeight - rect.top) - top));
    // Off screen, or unchanged: nothing worth posting.
    if (height === 0 || frame.plateformeBand === top + ":" + height) {
      return;
    }
    frame.plateformeBand = top + ":" + height;
    frame.contentWindow.postMessage({source: "plateforme-accueil", type: "viewport", top: top, height: height}, "*");
  }

  let scheduled = null;

  function schedule() {
    if (scheduled === null) {
      scheduled = window.requestAnimationFrame(function() {
        scheduled = null;
        frames().forEach(publishViewport);
      });
    }
  }

  window.addEventListener("message", function(evt) {
    const data = evt.data;
    if (!data || data.source !== "plateforme-accueil" || data.type !== "resize") {
      return;
    }
    frames().forEach(function(frame) {
      if (frame.contentWindow === evt.source) {
        frame.style.height = data.height + "px";
        // A taller iframe is a different band, and this message proves the page
        // is listening — our first viewport may have predated it. Force a resend.
        frame.plateformeBand = null;
        schedule();
      }
    });
  });

  window.addEventListener("scroll", schedule, {passive: true});
  window.addEventListener("resize", schedule);
  window.addEventListener("load", schedule);

  // Last: the iframe must not load before the listener above is installed, or
  // its first resize message is lost.
  frames().forEach(function(frame) {
    frame.src = frame.dataset.plateformeAccueil;
  });
})();
