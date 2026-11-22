// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=8911-1042
// source=les-emplois itou/templates/apply/includes/transition_logs.html, itou-theme stories/ItouListStep.stories.js
// component=Step list
const figma = require('figma')
const instance = figma.selectedInstance

const count = instance.getEnum('Number', { 1: 1, 2: 2, 3: 3, 4: 4, 5: 5 })

// Most recent event first: CSS highlights the first <li>.
// One <li> per nested "Step list item" instance (rendered by step-list-item.figma.js when connected).
const connected = instance.findConnectedInstances(() => true)
const items = connected.length
  ? connected.slice(0, count).map((item) => figma.html`
${item.executeTemplate().example}`)
  : Array.from({ length: count }, () => figma.html`
    <li>
        <time datetime="{{ log.timestamp.isoformat }}">Le {{ log.timestamp|date:dt_format }}</time>
        <span>Passé en "{{ log.pretty_to_state }}" par {{ log.user.get_inverted_full_name }}</span>
    </li>`)

export default {
  example: figma.html`<ul class="list-step">${items}
</ul>`,
  id: 'step-list',
  metadata: { nestable: true },
}
