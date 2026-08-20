/* Optimism calendar — progressively enhanced week view.
 * Fetches availability JSON from the same-process /calendar-data endpoint
 * (public) and re-renders the slot list when the user navigates weeks.
 * Without JavaScript the server-rendered initial week is fully usable.
 */
(function () {
  "use strict";

  var config = window.OPTIMISM_CALENDAR;
  if (!config) {
    return;
  }

  var container = document.getElementById("calendar-days");
  var weekLabel = document.getElementById("week-label");
  var prevButton = document.getElementById("prev-week");
  var nextButton = document.getElementById("next-week");
  if (!container || !weekLabel || !prevButton || !nextButton) {
    return;
  }

  var currentStart = parseDate(config.initialStart);
  var currentEnd = parseDate(config.initialEnd);

  function parseDate(iso) {
    var parts = iso.split("-");
    return new Date(Date.UTC(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10)));
  }

  function isoDate(date) {
    return date.toISOString().slice(0, 10);
  }

  function escapeHtml(value) {
    var div = document.createElement("div");
    div.textContent = value;
    return div.innerHTML;
  }

  function renderDays(calendar) {
    container.innerHTML = "";
    (calendar.dates || []).forEach(function (day) {
      var section = document.createElement("section");
      section.className = "calendar-day";
      section.setAttribute("aria-label", day.date.slice(0, 10));

      var heading = document.createElement("h3");
      heading.textContent = day.date.slice(0, 10);
      section.appendChild(heading);

      var slots = (day.resources && day.resources[0] && day.resources[0].slots) || [];
      if (slots.length === 0) {
        var none = document.createElement("p");
        none.textContent = "No availability.";
        section.appendChild(none);
      } else {
        var list = document.createElement("ul");
        list.className = "slot-list";
        slots.forEach(function (slot) {
          var item = document.createElement("li");
          if (slot.status === "available") {
            var button = document.createElement("button");
            button.type = "submit";
            button.name = "slot";
            button.value = slot.starts + "|" + slot.ends;
            button.className = "button slot-button";
            button.textContent = slot.starts.slice(11, 16) + " \u2013 " + slot.ends.slice(11, 16);
            item.appendChild(button);
          } else {
            var span = document.createElement("span");
            span.className = "slot-unavailable";
            span.setAttribute("aria-disabled", "true");
            span.textContent = slot.starts.slice(11, 16) + " \u2013 " + slot.ends.slice(11, 16) + " (unavailable)";
            item.appendChild(span);
          }
          list.appendChild(item);
        });
        section.appendChild(list);
      }
      container.appendChild(section);
    });
  }

  function loadWeek(start, end) {
    var url = "/calendar-data?start=" + isoDate(start) + "&end=" + isoDate(end) + "&resource=" + config.resourceId;
    weekLabel.textContent = isoDate(start) + " to " + isoDate(end);
    fetch(url)
      .then(function (response) {
        return response.json();
      })
      .then(function (data) {
        if (data.error) {
          weekLabel.textContent = "Unable to load calendar.";
          return;
        }
        renderDays(data);
      })
      .catch(function () {
        weekLabel.textContent = "Unable to load calendar.";
      });
  }

  prevButton.addEventListener("click", function () {
    currentStart = new Date(currentStart.getTime() - 7 * 86400000);
    currentEnd = new Date(currentEnd.getTime() - 7 * 86400000);
    loadWeek(currentStart, currentEnd);
  });

  nextButton.addEventListener("click", function () {
    currentStart = new Date(currentStart.getTime() + 7 * 86400000);
    currentEnd = new Date(currentEnd.getTime() + 7 * 86400000);
    loadWeek(currentStart, currentEnd);
  });
})();
