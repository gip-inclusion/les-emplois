// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=12716-18
// source=itou/templates/signup/includes/login_reminder.html
// component=hr with text
const figma = require('figma')
const instance = figma.selectedInstance

const text = instance.getString('Texte')

export default {
  example: figma.html`<hr class="my-5" data-it-text="${text}">`,
  id: 'horizontal-rule-with-text',
  metadata: { nestable: true },
}
