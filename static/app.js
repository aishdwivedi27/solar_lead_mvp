// Builds the address form as a stack of address blocks (street/city/state/
// postal/country + rebuild checkbox) instead of a fixed table of rows, with
// a "+ Add another address" button to append more, up to MAX_FORM_ROWS.
(function () {
  var maxRows = window.MAX_FORM_ROWS || 20;
  var list = document.getElementById("address-list");
  var addBtn = document.getElementById("add-address-btn");
  var nextIndex = 0;

  var FIELDS = [
    { key: "street_address", label: "Street address", placeholder: "e.g. 55 Currie St", required: true },
    { key: "city", label: "City", placeholder: "" },
    { key: "state_region", label: "State / Region", placeholder: "" },
    { key: "postal_code", label: "Postal / ZIP code", placeholder: "" },
    { key: "country", label: "Country", placeholder: "e.g. Australia", required: true, list: "country-list" },
  ];

  function updateAddButtonVisibility() {
    addBtn.hidden = nextIndex >= maxRows;
  }

  function updateRemoveButtons() {
    var blocks = list.querySelectorAll(".address-block");
    blocks.forEach(function (block) {
      var removeBtn = block.querySelector(".remove-address-btn");
      removeBtn.hidden = blocks.length <= 1;
    });
  }

  function addAddressBlock() {
    if (nextIndex >= maxRows) return;
    var index = nextIndex++;

    var block = document.createElement("div");
    block.className = "address-block";
    block.dataset.index = index;
    block.dataset.confirmed = "false";

    var header = document.createElement("div");
    header.className = "address-block-header";

    var title = document.createElement("span");
    title.className = "address-block-title";
    title.textContent = "Address " + (list.children.length + 1);
    header.appendChild(title);

    var removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "remove-address-btn";
    removeBtn.setAttribute("aria-label", "Remove this address");
    removeBtn.textContent = "×";
    removeBtn.addEventListener("click", function () {
      block.remove();
      renumberBlocks();
      updateRemoveButtons();
      updateAddButtonVisibility();
    });
    header.appendChild(removeBtn);

    block.appendChild(header);

    var grid = document.createElement("div");
    grid.className = "address-grid";

    FIELDS.forEach(function (field) {
      var label = document.createElement("label");
      label.className = "field";

      var span = document.createElement("span");
      span.className = "field-label";
      span.textContent = field.label;
      if (field.required) {
        var asterisk = document.createElement("span");
        asterisk.className = "required-marker";
        asterisk.setAttribute("aria-hidden", "true");
        asterisk.textContent = " *";
        span.appendChild(asterisk);
      }
      label.appendChild(span);

      var input = document.createElement("input");
      input.type = "text";
      input.name = field.key + "_" + index;
      input.autocomplete = "off";
      if (field.placeholder) input.placeholder = field.placeholder;
      if (field.required) input.required = true;
      if (field.list) input.setAttribute("list", field.list);
      label.appendChild(input);

      grid.appendChild(label);
    });

    // Any edit to an already-confirmed address invalidates that confirmation
    // and clears whatever suggestion box was showing for it.
    grid.addEventListener("input", function () {
      block.dataset.confirmed = "false";
      removeSuggestion(block);
    });

    var checkboxLabel = document.createElement("label");
    checkboxLabel.className = "field field-checkbox";
    var checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.name = "demolition_" + index;
    checkbox.value = "true";
    var checkboxText = document.createElement("span");
    checkboxText.textContent = "Rebuild planned";
    var infoIcon = document.createElement("span");
    infoIcon.className = "info-icon";
    infoIcon.tabIndex = 0;
    infoIcon.title = "Check this if the existing structure will be demolished to build a new house/building.";
    infoIcon.textContent = "i";
    checkboxLabel.appendChild(checkbox);
    checkboxLabel.appendChild(checkboxText);
    checkboxLabel.appendChild(infoIcon);
    grid.appendChild(checkboxLabel);

    block.appendChild(grid);
    list.appendChild(block);

    updateRemoveButtons();
    updateAddButtonVisibility();
  }

  function renumberBlocks() {
    var blocks = list.querySelectorAll(".address-block");
    blocks.forEach(function (block, i) {
      block.querySelector(".address-block-title").textContent = "Address " + (i + 1);
    });
  }

  addBtn.addEventListener("click", addAddressBlock);

  addAddressBlock();

  function removeSuggestion(block) {
    var existing = block.querySelector(".address-suggestion");
    if (existing) existing.remove();
  }

  function collectBlockValues(block) {
    var index = block.dataset.index;
    function val(key) {
      var input = block.querySelector('[name="' + key + "_" + index + '"]');
      return input ? input.value.trim() : "";
    }
    return {
      street_address: val("street_address"),
      city: val("city"),
      state_region: val("state_region"),
      postal_code: val("postal_code"),
      country: val("country"),
    };
  }

  function applySuggested(block, suggested) {
    var index = block.dataset.index;
    ["street_address", "city", "state_region", "postal_code"].forEach(function (key) {
      if (!suggested || suggested[key] === undefined) return;
      var input = block.querySelector('[name="' + key + "_" + index + '"]');
      if (input) input.value = suggested[key];
    });
  }

  function showSuggestion(block, result) {
    removeSuggestion(block);

    var box = document.createElement("div");
    box.className = "address-suggestion";

    var text = document.createElement("p");
    if (result.resolved_display_name) {
      text.appendChild(document.createTextNode("We found a close match: "));
      var strong = document.createElement("strong");
      strong.textContent = result.resolved_display_name;
      text.appendChild(strong);
    } else {
      text.textContent = "We couldn't confirm this address. Please double-check the spelling.";
    }
    box.appendChild(text);

    var actions = document.createElement("div");
    actions.className = "address-suggestion-actions";

    if (result.resolved_display_name) {
      var useSuggested = document.createElement("button");
      useSuggested.type = "button";
      useSuggested.className = "btn";
      useSuggested.textContent = "Use this address";
      useSuggested.addEventListener("click", function () {
        applySuggested(block, result.suggested);
        block.dataset.confirmed = "true";
        removeSuggestion(block);
      });
      actions.appendChild(useSuggested);
    }

    var keepAsEntered = document.createElement("button");
    keepAsEntered.type = "button";
    keepAsEntered.className = "btn btn-secondary";
    keepAsEntered.textContent = "Keep as entered";
    keepAsEntered.addEventListener("click", function () {
      block.dataset.confirmed = "true";
      removeSuggestion(block);
    });
    actions.appendChild(keepAsEntered);

    box.appendChild(actions);
    block.appendChild(box);
  }

  function validateBlock(block) {
    var values = collectBlockValues(block);
    if (!values.street_address) {
      block.dataset.confirmed = "true";
      return Promise.resolve();
    }
    return fetch("/api/addresses/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(values),
    })
      .then(function (response) {
        if (!response.ok) throw new Error("Address validation request failed");
        return response.json();
      })
      .then(function (result) {
        if (result.needs_confirmation) {
          showSuggestion(block, result);
        } else {
          block.dataset.confirmed = "true";
        }
      })
      .catch(function () {
        // Fail open: a transient network/API error here must never block
        // submission -- the main pipeline's own low_confidence_geocode flag
        // is the backstop for addresses that couldn't be pre-checked.
        block.dataset.confirmed = "true";
      });
  }

  // Address confirmation gate: before the (slow) pipeline runs, cheaply
  // geocode each entered address and, whenever it doesn't closely match what
  // was typed, make the user confirm or correct it. Only once every address
  // block is confirmed does the real submit (with its loading overlay) fire.
  var form = document.getElementById("addresses-form");
  var submitBtn = document.getElementById("submit-btn");
  var overlay = document.getElementById("loading-overlay");
  var addressGateInProgress = false;
  var addressGatePassed = false;

  function isConfirmed(block) {
    return block.dataset.confirmed === "true";
  }

  function submitForReal() {
    addressGatePassed = true;
    if (typeof form.requestSubmit === "function") {
      form.requestSubmit();
    } else {
      submitBtn.disabled = true;
      submitBtn.textContent = "Processing…";
      overlay.hidden = false;
      form.submit();
    }
  }

  function runAddressConfirmationGate() {
    if (addressGateInProgress) return;

    var blocks = Array.prototype.slice.call(list.querySelectorAll(".address-block"));
    var blocksToCheck = blocks.filter(function (block) { return !isConfirmed(block); });

    if (blocksToCheck.length === 0) {
      submitForReal();
      return;
    }

    addressGateInProgress = true;
    submitBtn.disabled = true;
    submitBtn.textContent = "Checking addresses…";

    Promise.all(blocksToCheck.map(validateBlock)).then(function () {
      addressGateInProgress = false;
      submitBtn.disabled = false;
      submitBtn.textContent = "Get estimates";
      if (blocks.every(isConfirmed)) {
        submitForReal();
      }
      // Otherwise, suggestion boxes are now showing -- wait for the user to
      // resolve each one and click "Get estimates" again.
    });
  }

  // The pipeline makes several sequential network calls per address (geocoding,
  // building lookups, PVGIS, NDVI, canopy height) and can take a minute or more
  // per address on a cold cache, so show a blocking status overlay for the wait
  // rather than leaving the page looking frozen after submit.
  if (form && submitBtn && overlay) {
    form.addEventListener("submit", function (event) {
      if (!form.checkValidity()) return;
      if (addressGatePassed) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Processing…";
        overlay.hidden = false;
        return;
      }
      event.preventDefault();
      runAddressConfirmationGate();
    });
  }
})();
