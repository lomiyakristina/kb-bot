
(() => {
  const params = new URLSearchParams(location.search);
  const id = params.get("export");
  if (!id) return;
  document.body.classList.add("export");
  const wait = () => {
    const el = document.getElementById("slide-" + id);
    if (!el) { requestAnimationFrame(wait); return; }
    document.querySelectorAll(".slide").forEach(s => s.classList.remove("export-target"));
    el.classList.add("export-target");
    document.documentElement.style.background = "#fffaf5";
    document.body.style.background = "#fffaf5";
    document.body.style.margin = "0";
    // signal ready
    document.title = "READY:" + id;
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wait);
  else wait();
})();