// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=12225-360
// source=les-emplois: itou/static/js/easymde_config.js (toolbar entries) ; the button itself is generated at runtime by EasyMDE 2.18 (vendor/easymde)
// component=Markdown_Button
const figma = require('figma')
const instance = figma.selectedInstance

// Hover is a CSS state only (EasyMDE stylesheet): same markup for both values.
const state = instance.getEnum('State', { Default: '', Hover: '' })

// Never hand-written: EasyMDE builds one button per toolbar entry declared in easymde_config.js
// (bold, italic, unordered-list, ordered-list, link). Shown here: the "bold" entry.
export default {
  example: figma.html`<button class="bold${state}" type="button" title="Gras" tabindex="-1">
    <i class="ri ri-bold ri-lg"></i>
</button>`,
  id: 'markdown-button',
  metadata: { nestable: true },
}
