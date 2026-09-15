// Stage 14 (manual override and recompute): lets an assessor who has verified
// a flagged address correct the specific input and rerun scoring/narrative
// against it, via POST /api/addresses/{id}/recompute, then patches that row
// in place with the response instead of reloading the whole results page.
(function () {
  var table = document.querySelector(".card .table-scroll table");
  if (!table) return;

  table.addEventListener("click", function (event) {
    var toggleId = event.target.getAttribute("data-toggle-edit");
    var cancelId = event.target.getAttribute("data-cancel-edit");
    if (toggleId) {
      var row = document.getElementById("edit-row-" + toggleId);
      if (row) row.hidden = !row.hidden;
    } else if (cancelId) {
      var cancelRow = document.getElementById("edit-row-" + cancelId);
      if (cancelRow) cancelRow.hidden = true;
    }
  });

  function fieldOrNull(form, name) {
    var el = form.elements[name];
    if (!el) return null;
    if (el.type === "checkbox") return el.checked ? true : null;
    var value = el.value;
    if (value === "") return null;
    if (value === "true") return true;
    if (value === "false") return false;
    return Number(value);
  }

  function applyRecordToRow(recordId, record) {
    var row = document.querySelector('.record-row[data-record-id="' + recordId + '"]');
    if (!row) return;

    row.querySelector(".cell-path").textContent = record.pipeline_path;

    var tierCell = row.querySelector(".cell-tier");
    if (record.tier === "HIGH") {
      tierCell.innerHTML = '<span class="badge badge-high">High</span>';
    } else if (record.tier === "MEDIUM") {
      tierCell.innerHTML = '<span class="badge badge-medium">Medium</span>';
    } else if (record.tier === "LOW") {
      tierCell.innerHTML = '<span class="badge badge-low">Low</span>';
    } else if (record.optimal_tilt_degrees !== null && record.optimal_tilt_degrees !== undefined) {
      tierCell.innerHTML =
        '<span class="badge badge-new-build">New build</span><br>' +
        '<span class="muted">Tilt ' + record.optimal_tilt_degrees + '°, azimuth ' +
        record.optimal_azimuth_degrees + '°</span>';
    } else {
      tierCell.innerHTML = '<span class="muted">&mdash;</span>';
    }

    row.querySelector(".cell-irradiance").textContent =
      record.regional_irradiance !== null && record.regional_irradiance !== undefined
        ? record.regional_irradiance
        : "—";
    row.querySelector(".cell-shaded").textContent =
      record.estimated_shaded_hours !== null && record.estimated_shaded_hours !== undefined
        ? Math.round(record.estimated_shaded_hours)
        : "—";
    var narrativeCell = row.querySelector(".cell-narrative");
    if (record.narrative) {
      narrativeCell.textContent = record.narrative;
    } else {
      narrativeCell.textContent = "";
      var reasonSpan = document.createElement("span");
      reasonSpan.className = "muted";
      reasonSpan.title = record.narrative_unavailable_reason || "";
      reasonSpan.textContent = "Narrative unavailable — " + (record.narrative_unavailable_reason || "");
      narrativeCell.appendChild(reasonSpan);
    }

    var linksCell = row.querySelector(".cell-links");
    linksCell.innerHTML = "";
    if (record.google_maps_link) {
      var mapsLink = document.createElement("a");
      mapsLink.href = record.google_maps_link;
      mapsLink.target = "_blank";
      mapsLink.rel = "noopener";
      mapsLink.textContent = "Google Maps";
      linksCell.appendChild(mapsLink);
    }
    if (record.street_view_link) {
      var streetLink = document.createElement("a");
      streetLink.href = record.street_view_link;
      streetLink.target = "_blank";
      streetLink.rel = "noopener";
      streetLink.textContent = "Street View";
      linksCell.appendChild(streetLink);
    }

    var confidenceBadge = row.querySelector(".cell-confidence");
    confidenceBadge.textContent = record.confidence === "verified" ? "Verified" : "Estimated";
    confidenceBadge.classList.toggle("badge-verified", record.confidence === "verified");
    confidenceBadge.classList.toggle("badge-estimated", record.confidence !== "verified");
  }

  table.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.classList.contains("edit-form")) return;
    event.preventDefault();

    var recordId = form.getAttribute("data-record-id");
    var statusEl = form.querySelector(".edit-status");
    var submitBtn = form.querySelector('button[type="submit"]');
    var corrections = {
      confirmed_building_exists: fieldOrNull(form, "confirmed_building_exists"),
      confirmed_adjacent_structure: fieldOrNull(form, "confirmed_adjacent_structure"),
      confirmed_geocode_accurate: fieldOrNull(form, "confirmed_geocode_accurate"),
      corrected_canopy_height_m: fieldOrNull(form, "corrected_canopy_height_m"),
    };

    submitBtn.disabled = true;
    statusEl.textContent = "Recomputing…";

    fetch("/api/addresses/" + recordId + "/recompute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(corrections),
    })
      .then(function (response) {
        if (!response.ok) throw new Error("Recompute failed");
        return response.json();
      })
      .then(function (record) {
        applyRecordToRow(recordId, record);
        statusEl.textContent = "Recomputed.";
        document.getElementById("edit-row-" + recordId).hidden = true;
      })
      .catch(function () {
        statusEl.textContent = "Could not recompute — please try again.";
      })
      .finally(function () {
        submitBtn.disabled = false;
      });
  });
})();
