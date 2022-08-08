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
        // Check everytime something change in the form
        form.change(checkValidity)
        form.on("duetChange", checkValidity)
        // Check immediately
        checkValidity({"currentTarget": this})
    });
});
