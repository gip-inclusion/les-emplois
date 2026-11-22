// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=8202-35845
// source=itou/templates/dashboard/includes/prescriber_job_seekers_card.html (counter badges of the dashboard cards)
// component=Comptage
const figma = require('figma')
const instance = figma.selectedInstance

const color = instance.getEnum('State', {
  'Action attendue': 'bg-info',
  Information: 'bg-info-lighter text-info',
  'Action urgente attendue': 'bg-warning',
})
const badge = instance.findInstance('Badges')
const count = badge && badge.type === 'INSTANCE' ? badge.getString('Text') : '1'

export default {
  example: figma.html`<span class="badge rounded-pill badge-xs ${color}">${count}</span>`,
  id: 'counter-badge',
  metadata: { nestable: true },
}
