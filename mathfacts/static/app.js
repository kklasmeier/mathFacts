/* Math Facts client script. Progressive: every page works without it.
 *
 * - Scales each sheet preview to the width of its frame.
 * - Keeps the builder preview in step with the form as the parent types.
 * - Wires up Print buttons (no inline handlers, so the CSP stays strict).
 */
(function () {
  "use strict";

  function scaleSheets(root) {
    (root || document).querySelectorAll(".preview-frame").forEach(function (frame) {
      var sheet = frame.querySelector(".sheet");
      if (!sheet) {
        return;
      }
      sheet.style.transform = "";
      var natural = sheet.offsetWidth;
      var scale = Math.min(1, frame.clientWidth / natural);
      sheet.style.transformOrigin = "top left";
      if (scale < 1) {
        sheet.style.transform = "scale(" + scale + ")";
      }
      frame.style.height = sheet.offsetHeight * scale + "px";
    });
  }

  function clear(node) {
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function initBuilder() {
    var form = document.getElementById("builder-form");
    if (!form) {
      return;
    }
    var preview = document.getElementById("preview");
    var summary = document.getElementById("preview-summary");
    var notices = document.getElementById("preview-notices");
    var errors = document.getElementById("preview-errors");
    var suggest = document.getElementById("preview-suggest");
    var tokenMeta = document.querySelector('meta[name="csrf-token"]');
    var timer = null;

    function showList(list, items) {
      clear(list);
      items.forEach(function (text) {
        var li = document.createElement("li");
        li.textContent = text;
        list.appendChild(li);
      });
    }

    function refresh() {
      var data = new FormData(form);
      data.delete("action");
      fetch(form.getAttribute("data-preview-url"), {
        method: "POST",
        body: data,
        credentials: "same-origin",
        headers: {
          "X-CSRFToken": tokenMeta ? tokenMeta.content : "",
          "Accept": "application/json",
        },
      })
        .then(function (response) {
          return response.json().then(function (body) {
            return { ok: response.ok, body: body };
          });
        })
        .then(function (result) {
          if (result.ok && result.body.ok) {
            preview.innerHTML = result.body.html;
            summary.textContent = result.body.summary + " " + result.body.auto;
            showList(notices, result.body.notices);
            suggest.hidden = !result.body.suggest_landscape;
            showList(errors, []);
            scaleSheets(preview);
          } else {
            var messages = Object.keys(result.body.errors || {}).map(function (key) {
              return result.body.errors[key];
            });
            showList(errors, messages);
          }
        })
        .catch(function () {
          showList(errors, ["The preview could not update. Check the connection and try again."]);
        });
    }

    function schedule() {
      window.clearTimeout(timer);
      timer = window.setTimeout(refresh, 250);
    }

    form.addEventListener("input", schedule);
    form.addEventListener("change", schedule);
  }

  function initAidField() {
    var form = document.getElementById("rate-form");
    var field = document.getElementById("aid-field");
    if (!form || !field) {
      return;
    }
    function sync() {
      var chosen = form.querySelector('input[name="support"]:checked');
      field.hidden = !(chosen && chosen.value !== "3");
    }
    form.addEventListener("change", sync);
    sync();
  }

  function initPrintButtons() {
    document.querySelectorAll("[data-print]").forEach(function (button) {
      button.addEventListener("click", function () {
        window.print();
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    scaleSheets(document);
    initBuilder();
    initAidField();
    initPrintButtons();
    window.addEventListener("resize", function () {
      scaleSheets(document);
    });
  });
})();
