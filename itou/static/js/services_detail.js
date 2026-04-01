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

function initCopyLink() {
    const btn = document.getElementById("js-copy-link");
    if (!btn) return;
    btn.addEventListener("click", function () {
        navigator.clipboard.writeText(window.location.href);
    });
}

initCopyLink();

function initCopyEmail() {
    const btn = document.getElementById("js-copy-email");
    if (!btn) return;
    btn.addEventListener("click", function () {
        navigator.clipboard.writeText(btn.dataset.email);
        const icon = btn.querySelector("i");
        icon.classList.replace("ri-file-copy-line", "ri-check-line");
        icon.classList.add("text-success");
        setTimeout(function () {
            icon.classList.replace("ri-check-line", "ri-file-copy-line");
            icon.classList.remove("text-success");
        }, 2000);
    });
}

initCopyEmail();
