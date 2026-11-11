/********************************************************************
  One-shot survey: can our users' devices use passkeys (WebAuthn)?

  Runs once per user and browser, never prompts the user, and reports
  the result to Matomo as an event (the user ID is already set there).
  Bump the version in `surveyVersion` to run the survey again later.

  Example use:
  <script src='{% static "js/webauthn_survey.js" %}' data-emplois-user-id="{{ request.user.pk }}"></script>
********************************************************************/
"use strict";

(function() {
  const surveyVersion = "v1";
  const storageKey = `emplois-webauthn-survey-${surveyVersion}-${document.currentScript.dataset.emploisUserId}`;

  async function survey() {
    if (localStorage.getItem(storageKey)) {
      return;
    }
    let result = "webauthn-absent";
    if (window.PublicKeyCredential) {
      const uvpaa = await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable();
      // getClientCapabilities() is only available in recent browsers.
      const capabilities = PublicKeyCredential.getClientCapabilities ? await PublicKeyCredential.getClientCapabilities() : {};
      result = `uvpaa:${uvpaa} hybrid:${capabilities.hybridTransport ?? "inconnu"}`;
    }
    window._paq = window._paq || [];
    window._paq.push(["trackEvent", "webauthn", `sondage-${surveyVersion}`, result]);
    localStorage.setItem(storageKey, "1");
  }

  // Never let the survey get in the user's way: any failure is silently ignored.
  window.addEventListener("load", () => survey().catch(() => {}));
})();
