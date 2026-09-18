"use strict";

const betaNotice = document.getElementById("directory-beta-notice");
const betaNoticeCookie = "notice_beta_hidden=1";

function hideBetaNotice() {
  betaNotice.classList.add("d-none");
  const expires = new Date(Date.now() + 15 * 24 * 60 * 60 * 1000).toUTCString();
  document.cookie = `${betaNoticeCookie}; expires=${expires}; path=/; SameSite=Lax`;
}

if (betaNotice) {
  if (!document.cookie.split("; ").includes(betaNoticeCookie)) {
    betaNotice.classList.remove("d-none");
  }
  document.getElementById("directory-beta-close").addEventListener("click", hideBetaNotice);
  document.getElementById("directory-beta-profile-link").addEventListener("click", hideBetaNotice);
}

const subject = document.getElementById("id_subject");
const customSubject = document.getElementById("id_custom_subject");
if (subject && customSubject) {
  const customSubjectContainer = customSubject.closest(".mb-3");
  const updateCustomSubject = () => {
    const visible = subject.value === "other";
    customSubjectContainer.hidden = !visible;
    customSubject.disabled = !visible;
  };
  subject.addEventListener("change", updateCustomSubject);
  updateCustomSubject();
}

const tallyHiddenFields = document.getElementById("directory-tally-hidden-fields");
if (tallyHiddenFields && window.Tally) {
  const formId = "RGyB44";
  const storageKey = "directory-tally-next-display";
  const nextDisplay = Number(localStorage.getItem(storageKey) || 0);
  if (Date.now() >= nextDisplay) {
    window.setTimeout(() => {
      let submitted = false;
      window.Tally.openPopup(formId, {
        width: 350,
        hideTitle: true,
        autoClose: 3000,
        hiddenFields: JSON.parse(tallyHiddenFields.textContent),
        onClose: () => {
          if (!submitted) {
            localStorage.setItem(storageKey, Date.now() + 5 * 60 * 60 * 1000);
          }
        },
        onSubmit: () => {
          submitted = true;
          localStorage.setItem(storageKey, Date.now() + 15 * 24 * 60 * 60 * 1000);
        },
      });
    }, 180000);
  }
}
