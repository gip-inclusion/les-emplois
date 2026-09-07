/********************************************************************
 *  Show tally form as a popup to prompt user for ease of access to job seeker's relevant informations.
 *
 *  Example use:
 *  {% load static %}
 *  <script async src="{{ TALLY_URL }}/widgets/embed.js"></script>
 *  <script src='{% static "js/nps_popup.js" %}' data-delaypopup="true" data-userkind="employeur" data-page="liste-candidatures"></script>
 *
 ********************************************************************/
"use strict";

const data = document.currentScript.dataset;

const tallyConfig = {
  "formId": "ZjMW2e",
  "popup": {
    "width": 400,
    "emoji": {
      "text": "👋",
      "animation": "wave"
    },
    "hiddenFields": {
      "Userkind": data.userkind,
      "Page": data.page
    },
    "hideTitle": true,
    "autoClose": 10000,
    "showOnce": false,
    "doNotShowAfterSubmit": true
  }
};

if (data.delaypopup == "true") {
  tallyConfig.popup.open = {
    "trigger": "time",
    "ms": 5000
  };
};

window.TallyConfig = tallyConfig;
