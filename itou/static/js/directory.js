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
  betaNotice.querySelector(".btn-close").addEventListener("click", hideBetaNotice);
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
