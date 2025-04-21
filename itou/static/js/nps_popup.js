/********************************************************************
  Show tally form as a popup to prompt user for NPS.

  Example use:
  {% load static %}
  <script async src="{{ TALLY_URL }}/widgets/embed.js"></script>
  <script src='{% static "js/nps_popup.js" %}' data-delaypopup="true" data-userkind="employeur" data-page="liste-candidatures"></script>

********************************************************************/

const data = document.currentScript.dataset;

const tallyConfig = {
  "formId": "3qzqeO",
  "popup": {
    "width": 300,
    "emoji": {
        "text": "👋",
        "animation": "wave"
    },
    "hiddenFields": {
        "Userkind": data.userkind,
        "Page": data.page
    },
    "hideTitle": true,
    "autoClose": 4000,
    "showOnce": true,
    "doNotShowAfterSubmit": true
  }
};

if (data.delaypopup == "true") {
  tallyConfig.popup.open = {
    "trigger": "time",
    "ms": 10000
  };
};

window.TallyConfig = tallyConfig;
