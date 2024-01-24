htmx.onLoad((target) => {

    /********************************************************************
       Send an event to Matomo on click.
       Usage with matomo-attributes tag:
            {% load matomo %}
            <a href="#" {% matomo_event "MyCategory" "MyAction" "MyOption" %} >
        Converted by simpletag to:
            <a href="#" data-matomo-event="true" data-matomo-category="MyCategory"
            data-matomo-action="MyAction" data-matomo-option="MyOption" >
    ********************************************************************/
    $('data-matomo-event="true"', target).on("click", function() {
        var category = $(this).data("matomo-category");
        var action = $(this).data("matomo-action");
        var option = $(this).data("matomo-option");

        _paq.push(['trackEvent', category, action, option]);
    });
});
