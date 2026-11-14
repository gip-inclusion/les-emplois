// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=4682-18748
// source=les-emplois itou/templates/companies/edit_job_description.html ({% block stepper %}), itou-theme stories/ItouStepper.stories.js
// component=Stepper
const figma = require('figma')
const instance = figma.selectedInstance

// Figma splits the line in two texts: "Étape 1" (bold) and "/3 : Informations générales".
const step = instance.getString('Step')
const stepName = instance.getString('Step name')
// .progress-bar-NN width classes are defined in les-emplois itou/static/css/itou.css.
const progress = instance.getEnum('Step n°', { 1: '33', 2: '66', 3: '100' })

export default {
  example: figma.html`<div class="c-stepper mb-3 mb-md-4">
    <div class="progress">
        <div class="progress-bar progress-bar-${progress}"
             role="progressbar"
             aria-valuenow="${progress}"
             aria-valuemin="0"
             aria-valuemax="100"
             aria-labelledby="currentProgressState"></div>
    </div>
    <p id="currentProgressState">
        <strong>${step}</strong>${stepName}
    </p>
</div>`,
  id: 'stepper',
  metadata: { nestable: true },
}
