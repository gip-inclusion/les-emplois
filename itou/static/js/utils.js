$(document).ready(() => {
    $(".js-prevent-default").on("click", (event) => {
        event.preventDefault();
    });

    $(".js-display-if-javascript-enabled").css("display", "block");

    /**
     * JS to disable the submit button of the form when it's not valid
     **/
    function checkValidity(e) {
        let submit = $(e.currentTarget).find('button[type="submit"]')
        if (e.currentTarget.checkValidity()) {
            submit.removeClass("disabled")
        } else {
            submit.addClass("disabled")
        }
    }

    $(".js-enable-submit-when-valid").each(function () {
        let form = $(this)
        // Check the validity when something (possibly) change in the form.
        form.on("change reset duetChange", (e) => {
          // Use setTimeout() to execute checkValidity() in the next event cycle,
          // when events *should* have done what they need to do.
          window.setTimeout(checkValidity, 0, e)
        })
        // Check immediately
        checkValidity({"currentTarget": this})
    });
});
