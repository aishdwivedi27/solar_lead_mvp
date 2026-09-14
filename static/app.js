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

  // The pipeline makes several sequential network calls per address (geocoding,
  // building lookups, PVGIS, NDVI, canopy height) and can take a minute or more
  // per address on a cold cache, so show a blocking status overlay for the wait
  // rather than leaving the page looking frozen after submit.
  var form = document.getElementById("addresses-form");
  var submitBtn = document.getElementById("submit-btn");
  var overlay = document.getElementById("loading-overlay");
  if (form && submitBtn && overlay) {
    form.addEventListener("submit", function () {
      if (!form.checkValidity()) return;
      submitBtn.disabled = true;
      submitBtn.textContent = "Processing…";
      overlay.hidden = false;
    });
  }
})();
