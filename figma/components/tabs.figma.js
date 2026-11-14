// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=10419-11889
// source=les-emplois itou/templates/companies/job_description_list.html ({% block title_extra %} .s-tabs-01__nav), includes/applications_orientations_tabs.html
// component=Tabs
const figma = require('figma')
const instance = figma.selectedInstance

const count = instance.getEnum('Number', { 2: 2, 3: 3, 4: 4, 5: 5 })
const current = instance.getEnum('Current', { 1: 1, 2: 2, 3: 3, 4: 4, 5: 5 })

// One <li> per nested "Tabs items" instance (rendered by tab-item.figma.js when connected).
const connected = instance.findConnectedInstances(() => true)
const items = connected.length
  ? connected.slice(0, count).map((item) => figma.html`
${item.executeTemplate().example}`)
  : Array.from({ length: count }, (_, i) => {
    const active = i + 1 === current ? ' active' : ''
    return figma.html`
    <li class="nav-item">
        <a class="nav-link${active}" href="…">Onglet ${i + 1}</a>
    </li>`
  })

// data-it-sliding-tabs-startindex keeps the active tab in view on small screens (0-based).
const startIndex = current > 1 && current <= count ? ` data-it-sliding-tabs-startindex="${current - 1}"` : ''

export default {
  example: figma.html`{% block title_extra %}
<ul class="s-tabs-01__nav nav nav-tabs mb-0" data-it-sliding-tabs="true"${startIndex}>${items}
</ul>
{% endblock %}`,
  id: 'tabs',
  metadata: { nestable: true },
}
