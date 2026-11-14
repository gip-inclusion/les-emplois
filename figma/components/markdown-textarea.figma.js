// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=12225-1118
// source=les-emplois: widget EasyMDEEditor (itou/utils/widgets.py, adds .easymde-box), toolbar in itou/static/js/easymde_config.js ; e.g. itou/www/companies_views/forms.py "description"
// component=Markdown_Textarea
const figma = require('figma')
const instance = figma.selectedInstance

const hasDescription = instance.getBoolean('Description')
const labelLayer = instance.findText('Label', { traverseInstances: true, path: ['_Form / Label'] })
const label = labelLayer && labelLayer.type === 'TEXT' ? labelLayer.textContent : 'Label'
const helpLayer = hasDescription
  ? instance.findText('Message', { traverseInstances: true, path: ["_Form / Texte d'aide"] })
  : undefined
const help = helpLayer && helpLayer.type === 'TEXT' ? helpLayer.textContent : "Texte d'aide"
const helpLine = hasDescription ? `\n    <div class="form-text" id="id_description_helptext">${help}</div>` : ''
const describedBy = hasDescription ? ' aria-describedby="id_description_helptext"' : ''

// Server markup only: EasyMDE (loaded by layout/base.html) replaces the .easymde-box textarea
// with its toolbar (see Markdown_Button) and editor. No placeholder: the textarea starts empty.
export default {
  example: figma.html`<div class="form-group">
    <label class="form-label" for="id_description">${label}</label>
    <textarea name="description" cols="40" rows="10" class="form-control easymde-box" id="id_description"${describedBy}></textarea>${helpLine}
</div>`,
  id: 'markdown-textarea',
  metadata: { nestable: true },
}
