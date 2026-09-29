"use strict";

(() => {
  const data = document.currentScript.dataset;
  const storageKey = `directory-tally-next-display-${data.userId}`;
  const hour = 60 * 60 * 1000;

  function nextDisplay() {
    return Number(localStorage.getItem(storageKey)) || 0;
  }

  function postpone(duration) {
    // Closing the popup after submission must preserve the longer, 15-day delay.
    localStorage.setItem(storageKey, Math.max(nextDisplay(), Date.now() + duration));
  }

  try {
    if (nextDisplay() > Date.now()) {
      return;
    }
    // Check that storage is writable before scheduling a recurring survey.
    localStorage.setItem(storageKey, "0");
  } catch {
    return;
  }

  setTimeout(() => {
    // Another tab may have dismissed or submitted the survey in the meantime.
    if (!window.Tally || nextDisplay() > Date.now()) {
      return;
    }
    window.Tally.openPopup("RGyB44", {
      width: 350,
      hideTitle: true,
      autoClose: 3000,
      doNotShowAfterSubmit: false,
      hiddenFields: {
        kind: data.kind,
        mail: data.mail,
        org: data.org,
        town: data.town,
      },
      onClose: () => postpone(5 * hour),
      onSubmit: () => postpone(15 * 24 * hour),
    });
  }, 180000);
})();
