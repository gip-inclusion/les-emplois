// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=5705-37948
// source=itou/templates/companies/includes/_card_jobdescription.html (ul.list-group.list-group-flush.list-group-link)
// component=listgroup
const figma = require('figma')
const instance = figma.selectedInstance

const connected = instance.findConnectedInstances(() => true)
const items = connected.length
  ? connected.map((item) => item.executeTemplate().example)
  : figma.html`
    <!-- Item listgroup -->`

export default {
  example: figma.html`<ul class="list-group list-group-flush list-group-link">${items}
</ul>`,
  id: 'list-group',
  metadata: { nestable: true },
}
