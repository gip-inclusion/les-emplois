function initDescriptionToggle() {
    const wrapper = document.getElementById("js-description-wrapper");
    const toggle = document.getElementById("js-description-toggle");
    const fade = document.getElementById("js-description-fade");
    if (!wrapper) return;
    if (wrapper.scrollHeight > wrapper.offsetHeight) {
        toggle.classList.remove("d-none");
        toggle.addEventListener("click", function (e) {
            e.preventDefault();
            wrapper.style.maxHeight = "none";
            wrapper.style.overflow = "visible";
            fade.remove();
            toggle.remove();
        });
    } else {
        fade.remove();
    }
}

initDescriptionToggle();
