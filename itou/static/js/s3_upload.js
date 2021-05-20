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
  const formValues = JSON.parse(
    document.getElementById(s3FormValuesId).textContent
  );
  const uploadConfig = JSON.parse(
    document.getElementById(s3UploadConfigId).textContent
  );

  // When a file is added to the drop zone, send a POST request to this URL.
  const formUrl = formValues["url"];

  // Submit button to be disabled during file processing
  const submitButton = $("button[type='submit']");

  // S3 form params sent when a new file is added to the drop zone.
  const formParams = formValues["fields"];

  // Appended before the file name. The final slash is added later.
  const keyPath = uploadConfig["key_path"];

  // Dropzone configuration
  const dropzoneConfig = {
    url: formUrl,
    params: formParams,
    maxFilesize: uploadConfig["max_file_size"], // in MB
    timeout: uploadConfig["timeout"], // default 3000, in ms
    maxFiles: uploadConfig["max_files"],
    acceptedFiles: uploadConfig["allowed_mime_types"],
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
      const fileKey = `${keyPath}/${filename}.${extension}`;
      // Add a file key to options params so that it's send
      // as an input field on POST.
      this.params["key"] = fileKey;
      return fileKey;
    },
  };

  // By default, Dropzone attaches to any component having the "dropzone" class.
  // Turn off this behavior to control all the aspects "manually".
  Dropzone.autoDiscover = false;

  const dropzone = new Dropzone(dropzoneSelector, dropzoneConfig);

  // Display a help message when the user tries to
  // submit the form during file transfer.
  submitButton.tooltip({ title: "Veuillez attendre la fin du transfert" });
  // Enable it later, during file transfer.
  submitButton.tooltip("disable");

  // Events
  dropzone.on("addedfile", function (file) {
    submitButton.tooltip("enable");
    submitButton.prop("disabled", true);
    submitButton.addClass("btn-secondary");
  });

  // Called when the upload was either successful or erroneous.
  dropzone.on("complete", function (file) {
    submitButton.tooltip("disable");
    submitButton.prop("disabled", false);
    submitButton.removeClass("btn-secondary");
  });

  dropzone.on("removedfile", function (file) {
    $(callbackLocationSelector).val("");
  });

  dropzone.on("success", function (file, xhr, formData) {
    const location = `${formUrl}/${file.upload.filename}`;
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
        `(${file.upload.progress} of ${file.upload.total}) to S3 ${formUrl}: ${errorMessage}`;
      $.post(sentryInternalUrl, {
        status_code: 500,
        error_message: sentryErrorMessage,
        csrfmiddlewaretoken: sentryCsrfToken,
      });
    }
  });
};
