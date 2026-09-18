"use strict";

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
