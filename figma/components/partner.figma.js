// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=8996-1214
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/forms-buttons-custom--docs (Partner) ; les-emplois itou/templates/dashboard/includes/job_seeker_job_applications_card.html
// component=Partner
const figma = require('figma')
const instance = figma.selectedInstance

const label = instance.getString('Label')
// Hover is CSS only.
instance.getEnum('State', { Default: 'default', Hover: 'hover' })

export default {
  example: figma.html`<a href="#" target="_blank" rel="noopener" class="btn btn-partner btn-partner--diagoriente">${label}</a>`,
  id: 'partner',
  metadata: { nestable: true },
}
