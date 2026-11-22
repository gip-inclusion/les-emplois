// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=5624-36623
// source=les-emplois: itou/templates/utils/widgets/file_input.html (+ file_input_constraints.html), widget ItouFileInput (itou/files/forms.py), JS initDropZone in itou/static/js/utils.js
// component=Drag and drop
const figma = require('figma')
const instance = figma.selectedInstance

// No component properties: label and help text live in nested "_Form / Label" / "_Form / Texte d'aide" instances.
const labelLayer = instance.findText('Label', { traverseInstances: true, path: ['_Form / Label'] })
const label = labelLayer && labelLayer.type === 'TEXT' ? labelLayer.textContent : 'Label'
const helpLayer = instance.findText('Message', { traverseInstances: true, path: ["_Form / Texte d'aide"] })
const help = helpLayer && helpLayer.type === 'TEXT' ? helpLayer.textContent : ''
const helpLine = help ? `\n    <div class="form-text" id="id_field_helptext">${help}</div>` : ''
const describedBy = help ? ' aria-describedby="id_field_helptext"' : ''

// Rendered by {% bootstrap_field form.field %} with widget=ItouFileInput(content_type="application/pdf", max_upload_size_mb=20).
// "Rechercher dans vos fichiers" is a <label> (stretched-link) pointing at the file input, not a <button>.
export default {
  example: figma.html`<div class="form-group">
    <label class="form-label" for="id_field">${label}</label>
    <div class="c-dropzone position-relative file-dropzone">
        <input type="file" name="field" accept="application/pdf" class="form-control" id="id_field"${describedBy}>
        <div class="file-dropzone-selector">
            <p class="mb-1 text-nuance-06" aria-hidden="true">
                <i class="ri-upload-cloud-2-line ri-2x" aria-hidden="true"></i>
            </p>
            <p class="mb-2">
                Glissez votre fichier ici ou <strong>rechercher</strong> dans vos fichiers
            </p>
            <label for="id_field" class="btn btn-link btn-sm btn-ico mb-2 stretched-link">
                <i class="ri-folder-line ri-xl" aria-hidden="true"></i>
                <span>Rechercher dans vos fichiers</span>
            </label>
            <p class="small text-nuance-06 mb-0">
                Taille maximale : 20 Mo
                <br>
                Type de fichier : PDF
            </p>
        </div>
        <div class="file-dropzone-preview d-none p-5">
            <p>Fichier sélectionné :</p>
            <div class="fs-sm mb-3">
                <strong class="file-dropzone-filename"></strong>
            </div>
            <button type="button" class="btn btn-sm btn-ico btn-secondary file-dropzone-clear">
                <i class="ri-delete-bin-line ri-xl" aria-hidden="true"></i>
                <span>Supprimer</span>
            </button>
        </div>
    </div>${helpLine}
</div>`,
  id: 'drag-and-drop',
  metadata: { nestable: true },
}
