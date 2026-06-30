/* JS to send a XHR when clicking a button or link to register a mobilization event
 * aka an iMER (intention de mise en relation) */
document.addEventListener("DOMContentLoaded", function() {
  const trackedLinks = document.querySelectorAll("[data-emplois-mobilization-kind]");
  const csrftoken = document.querySelector("[name=csrfmiddlewaretoken]").value;
  Array.from(trackedLinks).forEach(function(link) {
    link.addEventListener("click", function(event) {
      /* The target clicked may be a child, go up in the DOM */
      let el = event.target;
      while (!el.getAttribute("data-emplois-mobilization-kind")) {
        el = el.parentElement;
      }
      const kind = el.getAttribute("data-emplois-mobilization-kind");
      const externalLink = el.getAttribute("data-emplois-mobilization-external-link");
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "{% url "insertion_views:register_mobilization_event" %}");
      xhr.setRequestHeader("X-CSRFToken", csrftoken);
      xhr.setRequestHeader("Content-Type", "application/x-www-form-urlencoded");
      data = "kind=" + kind + "&structure_uid={{ structure_uid|default:"" }}&service_uid={{ service_uid|default:"" }}";
      if (externalLink) {
        data += "&service_external_link=" + externalLink;
      }
      xhr.send(data)
    });
  });
});
