(function () {
  function startPolling(target) {
    var url = target.dataset.pollUrl;
    var intervalSeconds = Number(target.dataset.pollInterval || "5");
    if (!url || target.dataset.polling === "1") {
      return;
    }
    target.dataset.polling = "1";

    function refresh() {
      fetch(url, {
        headers: {
          "X-Requested-With": "fetch"
        }
      })
        .then(function (response) {
          if (!response.ok) {
            throw new Error("status " + response.status);
          }
          return response.text();
        })
        .then(function (html) {
          var wrapper = document.createElement("div");
          wrapper.innerHTML = html.trim();
          var next = wrapper.firstElementChild;
          if (!next) {
            return;
          }
          target.replaceWith(next);
          target = next;
          if (next.classList.contains("status-completed") ||
              next.classList.contains("status-manual_review") ||
              next.classList.contains("status-failed")) {
            return;
          }
          window.setTimeout(refresh, Math.max(intervalSeconds, 1) * 1000);
        })
        .catch(function () {
          window.setTimeout(refresh, Math.max(intervalSeconds, 1) * 1000);
        });
    }

    refresh();
  }

  window.addEventListener("DOMContentLoaded", function () {
    var target = document.querySelector("[data-poll-url]");
    if (target) {
      startPolling(target);
    }
  });
})();
