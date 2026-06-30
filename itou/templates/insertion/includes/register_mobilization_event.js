/* JS to send a XHR when clicking a button or link to register a mobilization event
 * aka an iMER (intention de mise en relation) */
document.addEventListener("DOMContentLoaded", function() {
  const trackedLinks = document.querySelectorAll("[data-emplois-mobilization-kind]");
  const csrftoken = document.querySelector("[name=csrfmiddlewaretoken]").value;
  Array.from(trackedLinks).forEach(function(link) {
    link.addEventListener("click", function(event) {
      const kind = event.target.getAttribute("data-emplois-mobilization-kind");
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "{% url "insertion_views:register_mobilization_event" %}");
      xhr.setRequestHeader("X-CSRFToken", csrftoken);
      xhr.setRequestHeader("Content-Type", "application/x-www-form-urlencoded");
      xhr.send("kind=" + kind + "&structure_uid={{ structure_uid|default:"" }}&service_uid={{ service_uid|default:"" }}");
    });
  });
});
