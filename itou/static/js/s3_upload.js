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
    dictResponseError: "Erreur technique. Merci de recommencer.",
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

  // Events
  dropzone.on("addedfile", function (file) {
    submitButton.prepend(
      `<div class="spinner-border spinner-border-sm" role="status" aria-hidden="true">
        <span class="sr-only">Veuillez attendre la fin du transfert</span>
      </div>`);
    submitButton.prop("disabled", true);
    submitButton.addClass("btn-secondary");
  });

  // Called when the upload was either successful or erroneous.
  dropzone.on("complete", function (file) {
    submitButton.prop("disabled", false);
    submitButton.find(".spinner-border").remove();
    submitButton.removeClass("btn-secondary");
  });

  dropzone.on("removedfile", function (file) {
    $(callbackLocationSelector).val("");
  });

  dropzone.on("success", function (file, xhr, formData) {
    const location = `${formUrl}/${file.upload.filename}`;
    // Prevent a selector mistake from being silent.
    if ($(callbackLocationSelector).length === 0) {
      this._handleUploadError(
        [file],
        xhr,
        "Ce document n'a pas pu être envoyé à cause d'un problème technique. Nous vous invitons à contacter notre support."
      );
    }
    $(callbackLocationSelector).val(location);
  });

  dropzone.on("error", function (file, errorMessage, xhr) {
    let statusCode = 500;

    if (typeof errorMessage === "string") {
      if (errorMessage.includes("timedout")) {
        // Override default English message and don't send the error to Sentry.
        file.previewElement.querySelectorAll('[data-dz-errormessage]')[0].textContent = "Erreur technique. Merci de recommencer.";
        return
      }
    }
    else {
      // errorMessage is a JSON object. Display a nice message to the user instead of [object Object].
      file.previewElement.querySelectorAll('[data-dz-errormessage]')[0].textContent = "Erreur technique. Merci de recommencer.";
    }

    if (xhr) {
      statusCode = xhr.status;

      if (statusCode === 0) {
        // Don't send undefined errors to Sentry.
        // Might be due to a firewall or to an unreachable network.
        // See https://stackoverflow.com/questions/872206/what-does-it-mean-when-an-http-request-returns-status-code-0
        return
      }

      if (xhr.responseText) {
        let responseJson = JSON.parse(xhr.responseText);
        errorMessage = responseJson["Message"];
        // User waited too long before sending the file.
        // See base.py > STORAGE_UPLOAD_KINDS > upload expiration
        if (errorMessage === "Policy expired") {
          return
        }
      }

      // An error occurred with the request. Send it to Sentry to avoid silent bugs.
      const sentryErrorMessage =
        `Unable to upload "${file.upload.filename}" ` +
        `(${file.upload.progress} of ${file.upload.total}) to S3 ${formUrl}: ${errorMessage}`;
      $.post(sentryInternalUrl, {
        status_code: statusCode,
        error_message: sentryErrorMessage,
        csrfmiddlewaretoken: sentryCsrfToken,
      });
    }
  });
};
