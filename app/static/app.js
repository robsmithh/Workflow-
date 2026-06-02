// Show only the schedule fields relevant to the selected schedule type.
(function () {
  const select = document.getElementById("schedule_type");
  if (!select) return;

  const fields = document.querySelectorAll(".sched-field");
  function update() {
    const value = select.value;
    fields.forEach((el) => {
      el.style.display = el.dataset.for === value ? "" : "none";
    });
  }
  select.addEventListener("change", update);
  update();
})();

// After triggering a run, refresh once so the new run appears in history.
(function () {
  const params = new URLSearchParams(window.location.search);
  if (params.get("triggered")) {
    setTimeout(() => {
      const url = window.location.pathname;
      window.location.replace(url);
    }, 2500);
  }
})();
