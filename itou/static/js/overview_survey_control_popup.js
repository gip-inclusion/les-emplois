/********************************************************************
 *  Show tally form as a popup to prompt user for ease of access to job seeker's relevant informations.
 *  This form is meant for the control group of the experiment.
 ********************************************************************/
"use strict";

const data = document.currentScript.dataset;

const options = {
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
};

if (data.delaypopup == "true") {
  setTimeout(() => {
    Tally.openPopup("pbQgJV", options);
  }, 5000);
};
