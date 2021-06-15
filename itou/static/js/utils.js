$(document).ready(() => {
    $(".js-prevent-default").on("click", (event) => {
        event.preventDefault();
    });

    $(".js-display-if-javascript-enabled").css("display", "block");
});
