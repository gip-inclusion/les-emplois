"use strict";

function ready(fn) {
  if (document.readyState !== 'loading') {
    fn();
  } else {
    document.addEventListener('DOMContentLoaded', fn);
  }
}

ready(() => {
  const hideButton = document.getElementById("hide-btn")
  hideButton.addEventListener("click", function (event) {
    document.getElementById("djhj").style.display = "none"
  })
});
