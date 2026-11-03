// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=4294-18028
// source=les-emplois itou/templates/approvals/includes/progress_bar.html
// component=Progress
const figma = require('figma')
const instance = figma.selectedInstance

// .progress-bar-NN width classes are defined in les-emplois itou/static/css/itou.css.
const ratio = instance.getEnum('Etape', { 'Etape 1': '33', 'Etape 2': '66', 'Etape 3': '100' })

export default {
  example: figma.html`{% include "approvals/includes/progress_bar.html" with ratio=${ratio} only %}

<div class="progress">
    <div class="progress-bar progress-bar-${ratio}"
         role="progressbar"
         aria-valuenow="${ratio}"
         aria-valuemin="0"
         aria-valuemax="100"
         aria-labelledby="currentProgressState"></div>
</div>`,
  id: 'progress',
  metadata: { nestable: true },
}
