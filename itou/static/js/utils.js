$(document).ready(() => {
    $(".jsPreventDefault").on("click", (event) => {
        event.preventDefault();
    });

    $(".jsDisplayIfJavascriptEnabled").css("display", "block");
});
