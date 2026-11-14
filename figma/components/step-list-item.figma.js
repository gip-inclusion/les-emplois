// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=8911-1026
// source=les-emplois itou/templates/apply/includes/transition_logs.html, itou-theme stories/ItouListStep.stories.js
// component=Step list item
const figma = require('figma')
const instance = figma.selectedInstance

const date = instance.getString('Date')
const label = instance.getString('Label')
// Active = first <li> of the .list-step (highlighted by CSS); Only = the list has a single <li>
// (no connecting line). Both follow from the item's position: same markup.
instance.getEnum('Active', { On: true, Off: false })
instance.getEnum('Only', { On: true, Off: false })

export default {
  example: figma.html`<li>
    <time datetime="{{ log.timestamp.isoformat }}">${date}</time>
    <span>${label}</span>
</li>`,
  id: 'step-list-item',
  metadata: { nestable: true },
}
