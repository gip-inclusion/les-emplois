/********************************************************************
  Hand our Matomo consent and identity to the plateforme-accueil iframe.

  The embedded page has no consent banner and no visitor of its own: it
  measures nothing until this message arrives, then reports into our site,
  on our visit. The grant only fires once tarteaucitron has actually loaded
  the tracker, so a refusal reaches the iframe as silence.

  A withdrawal, though, has to be said out loud: the iframe outlives the click
  that revokes consent here, and it would otherwise keep measuring someone who
  asked us to stop.

  Sandboxed without allow-same-origin, the iframe has an opaque origin that
  no concrete targetOrigin matches, hence "*". The message only reaches this
  frame, and frame-src decides what may load in it.
********************************************************************/
"use strict";

(function() {
  let payload = null;

  function frames() {
    return document.querySelectorAll("iframe[data-plateforme-accueil]");
  }

  function publish(frame) {
    if (payload && frame.contentWindow) {
      frame.contentWindow.postMessage(payload, "*");
    }
  }

  window._paq = window._paq || [];
  window._paq.push([function() {
    payload = {
      source: "plateforme-accueil",
      type: "analytics",
      consent: true,
      visitorId: this.getVisitorId(),
      siteId: this.getSiteId(),
    };
    frames().forEach(publish);
  }]);

  document.addEventListener("matomo_disallowed", function() {
    payload = {source: "plateforme-accueil", type: "analytics", consent: false};
    frames().forEach(publish);
  });

  // Consent often lands before the iframe has loaded. Any message from it
  // proves it is listening, so publish again then.
  window.addEventListener("message", function(evt) {
    if (evt.data && evt.data.source === "plateforme-accueil") {
      frames().forEach(function(frame) {
        if (frame.contentWindow === evt.source) {
          publish(frame);
        }
      });
    }
  });
})();
