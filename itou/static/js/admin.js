(function () {
  document.addEventListener("DOMContentLoaded", function (event) {
    function handlePaste(event) {
      const pasted = event.clipboardData.getData("text");
      const cleaned = pasted.replaceAll(" ", "");
      if (/[0-9]{9,}/.test(cleaned)) {
        event.preventDefault();
        const field = event.target
        field.value = field.value.substring(0, field.selectionStart)
            + cleaned
            + field.value.substring(field.selectionEnd);
      }
    }

    for (const id of [
      "searchbar",
      "id_nir",
      "id_number", // PASS IAE
      "id_siret",
    ]) {
      const element = document.getElementById(id);
      if (element) {
        element.addEventListener("paste", handlePaste);
      }
    }
  });
  // Remove bootstrap CSS elements not needed for admin
  document.querySelectorAll(".input-group-append").forEach(elt => { elt.remove(); });
}());
