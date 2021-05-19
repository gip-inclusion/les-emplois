"use strict";

// Arguments
// - callbackLocationSelector: input field where the location URL will be provided
//   after success (ex. "#foo").
// - dropzoneSelector: transform this element into a drag and drop zone.
// - s3FormValuesId: ID of DOM element that contains the JSON values of the form (eg. URL, fields, etc)
// - s3UploadConfigId: ID of DOM element that contains the JSON values of the S3 config (eg. max file size,
//   timeout, etc).

window.s3UploadInit = function s3UploadInit({
  dropzoneSelector = "#resume_form",
  callbackLocationSelector = "",
  s3FormValuesId = "s3-form-values",
  s3UploadConfigId = "s3-upload-config",
  sentryInternalUrl = "",
  sentryCsrfToken = "",
} = {}) {
  const form_values = JSON.parse(
    document.getElementById(s3FormValuesId).textContent
  );
  const upload_config = JSON.parse(
    document.getElementById(s3UploadConfigId).textContent
  );

  // When a file is added to the drop zone, send a POST request to this URL.
  const form_url = form_values["url"];

  // Submit button to be disabled during file processing
  const submit_button = $("button[type='submit']");

  // S3 form params sent when a new file is added to the drop zone.
  const form_params = form_values["fields"];

  // Appended before the file name. The final slash is added later.
  const key_path = upload_config["key_path"];

  // Dropzone configuration
  const dropzone_config = {
    url: form_url,
    params: form_params,
    maxFilesize: upload_config["max_file_size"], // in MB
    timeout: upload_config["timeout"], // default 3000, in ms
    maxFiles: upload_config["max_files"],
    acceptedFiles: upload_config["allowed_mime_types"],
    addRemoveLinks: true,
    // translations
    dictFallbackMessage: "Ce navigateur n'est pas compatible",
    dictFileTooBig: "Fichier trop volumineux",
    dictInvalidFileType: "Type de fichier non pris en charge",
    dictResponseError: "Erreur technique",
    dictCancelUpload: "Annuler",
    dictUploadCanceled: "Annulé",
    dictCancelUploadConfirmation: "Voulez-vous vraiment annuler le transfert ?",
    dictRemoveFile: "Supprimer",
    dictRemoveFileConfirmation: "Voulez-vous vraiment supprimer le fichier ?",
    dictMaxFilesExceeded: "Un seul fichier autorisé à la fois",
    // the function will be used to rename the file.name before appending it to the formData
    renameFile: function (file) {
      const extension = file.name.split(".").pop();
      const filename = Dropzone.uuidv4();
      const file_key = `${key_path}/${filename}.${extension}`;
      // Add a file key to options params so that it's send
      // as an input field on POST.
      this.params["key"] = file_key;
      return file_key;
    },
  };

  // By default, Dropzone attaches to any component having the "dropzone" class.
  // Turn off this behavior to control all the aspects "manually".
  Dropzone.autoDiscover = false;

  const dropzone = new Dropzone(dropzoneSelector, dropzone_config);

  // Display a help message when the user tries to
  // submit the form during file transfer.
  submit_button.tooltip({ title: "Veuillez attendre la fin du transfert" });
  // Enable it later, during file transfer.
  submit_button.tooltip("disable");

  // Events
  dropzone.on("addedfile", function (file) {
    submit_button.tooltip("enable");
    submit_button.prop("disabled", true);
    submit_button.addClass("btn-secondary");
  });

  // Called when the upload was either successful or erroneous.
  dropzone.on("complete", function (file) {
    submit_button.tooltip("disable");
    submit_button.prop("disabled", false);
    submit_button.removeClass("btn-secondary");
  });

  dropzone.on("removedfile", function (file) {
    $(callbackLocationSelector).val("");
  });

  dropzone.on("success", function (file, xhr, formData) {
    const location = `${form_url}/${file.upload.filename}`;
    // Prevent a selector mistake from being silent.
    if ($(callbackLocationSelector).length == 0) {
      this._handleUploadError(
        [file],
        xhr,
        "Ce document n'a pas pu être envoyé à cause d'un problème technique. Nous vous invitons à contacter notre support."
      );
    }
    $(callbackLocationSelector).val(location);
  });

  dropzone.on("error", function (file, errorMessage, xhr) {
    if (xhr != null) {
      // An error occurred with the request.
      // Send it to Sentry to avoid silent bugs.
      const sentryErrorMessage =
        `Unable to upload "${file.upload.filename}" ` +
        `(${file.upload.progress} of ${file.upload.total}) to S3 ${form_url}: ${errorMessage}`;
      $.post(sentryInternalUrl, {
        status_code: 500,
        error_message: sentryErrorMessage,
        csrfmiddlewaretoken: sentryCsrfToken,
      });
    }
  });
};
