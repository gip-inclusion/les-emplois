"use strict"

document.querySelectorAll("duet-date-picker").forEach(pickerInstance => {

  pickerInstance.dateAdapter = {

    parse(value = "", createDate) {
      const DATE_FORMAT = /^(\d{2})\/(\d{2})\/(\d{4})$/
      const matches = value.match(DATE_FORMAT)
      if (matches) {
        return createDate(matches[3], matches[2], matches[1])
      }
    },

    format(date) {
      const day = ('0' + date.getDate()).slice(-2)
      const month = ('0' + `${date.getMonth() + 1}`).slice(-2)
      return `${day}/${month}/${date.getFullYear()}`
    },

  }

  // Automatically insert slashes '/' in date fields.
  pickerInstance.addEventListener("keyup", event => {
    // Do nothing when backspace was pressed.
    if (event.which !== 8) {
      const numChars = event.target.value.length
      if (numChars === 2 || numChars === 5) {
        event.target.value = `${event.target.value}/`
      }
    }
  })

  pickerInstance.localization = {
    buttonLabel: "Choisir une date",
    placeholder: "JJ/MM/AAAA",
    selectedDateMessage: "La date sélectionnée est",
    prevMonthLabel: "Mois précédent",
    nextMonthLabel: "Mois suivant",
    monthSelectLabel: "Mois",
    yearSelectLabel: "Année",
    closeLabel: "Fermer la fenêtre",
    calendarHeading: "Choisir une date",
    dayNames: ["Dimanche", "Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi"],
    monthNames: [
      "Janvier",
      "Février",
      "Mars",
      "Avril",
      "Mai",
      "Juin",
      "Juillet",
      "Août",
      "Septembre",
      "Octobre",
      "Novembre",
      "Décembre",
    ],
    monthNamesShort: ["Jan", "Fév", "Mar", "Avr", "Mai", "Jun", "Jui", "Aoû", "Sep", "Oct", "Nov", "Déc"],
    locale: "fr-FR",
  }

})
