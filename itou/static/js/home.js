$(document).ready(() => {
  $("#homeTabs a").on("click", (e) => {
    e.preventDefault();
    $(this).tab("show");
  });   

  $("#homeSearchTabs a").on("click", (e) => {
    e.preventDefault();
    $(this).tab("show");
  });

  showEvents();
});


let renderEvents = (response) => {
  let eventsNode = null;

  if (response.events.length > 0) {
    eventsNode = $('<div class="row">'); 

    for ( let event of response.events ) {
      let eventDate = event.date;
      const dateArray = eventDate.split(' ');
      let finalDate = dateArray[0].split('-');

      let eventNode = $('<div class="col-12 col-lg-4">'); 
      eventNode.html('<article class="pb-5 pb-lg-7"><figure class="mb-3"><img src="'+event.image.sizes.medium_large.url+'" class="img-fluid img-fitcover rounded has-ratio-16-9" alt="" /></figure><span class="badge badge-pill badge-primary text-white"><i class="ri-calendar-2-line mr-2"></i>Le '+finalDate[2]+'/'+finalDate[1]+'/'+finalDate[0]+'</span><h3 class="h2 mt-2">'+event.title+'</h3><div>'+event.excerpt+'</div><a href="'+event.url+'" class="font-weight-bold" target="_blank" title="(ouverture dans un nouvel onglet)">Voir l’événement</a><i class="ri-external-link-line ri-lg ml-1"></i></article>'); 
      eventNode.appendTo( eventsNode );       
    } 
  }

  eventsNode.appendTo($('#rest-events')); 
};


let showEvents = () => {
  $.ajax({ 
    url: 'https://communaute.inclusion.beta.gouv.fr/wp-json/tribe/events/v1/events', 
    method: 'GET', 
    data: { 'page': 1, 'per_page': 3, } 
  })
  .done(renderEvents)
};
