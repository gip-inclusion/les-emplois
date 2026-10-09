"use strict";

htmx.onLoad((target) => {
  const subject = target.querySelector("#id_subject");
  const customSubject = target.querySelector("#id_custom_subject");
  // Form is not displayed when user is rate-limited, not all HTMX fragment contain the form.
  if (subject && customSubject) {
    const customSubjectContainer = customSubject.closest(".form-group");
    function updateCustomSubject() {
      const visible = subject.value === "other";
      customSubjectContainer.classList.toggle("d-none", !visible);
      customSubject.disabled = !visible;
      subject.addEventListener("change", updateCustomSubject);
    }
    updateCustomSubject();
  }
});
