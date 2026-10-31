/* Theme switching, shared by all four pages. Loaded in <head> so the saved theme is applied before the
   first paint; the button in the header cycles through THEMES and the choice is kept in the browser's local storage.
   To add a theme: add its colours to themes.css and its name here. */
(function () {
  const THEMES = ["", "ocean", "forest", "contrast"];  // "" is the default (terracotta, no data-theme)
  const NAMES = {
    en: { label: "Theme", "": "Terracotta", ocean: "Ocean", forest: "Forest", contrast: "High contrast" },
    zh: { label: "主题", "": "赤陶", ocean: "海洋", forest: "森林", contrast: "高对比" },
  };
  const root = document.documentElement;
  const names = NAMES[/^zh/i.test(root.lang) ? "zh" : "en"];

  function saved() {
    try { const t = localStorage.getItem("theme") || ""; return THEMES.includes(t) ? t : ""; } catch (e) { return ""; }
  }
  function apply(t) { if (t) root.setAttribute("data-theme", t); else root.removeAttribute("data-theme"); }
  let current = saved();
  apply(current);

  document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("btn-theme");
    if (!btn) return;
    const show = () => {
      btn.textContent = names.label + (names === NAMES.zh ? "：" : ": ") + names[current];
      btn.setAttribute("aria-label", names.label + " — " + names[current]);
    };
    btn.addEventListener("click", () => {
      current = THEMES[(THEMES.indexOf(current) + 1) % THEMES.length];
      apply(current);
      try { if (current) localStorage.setItem("theme", current); else localStorage.removeItem("theme"); } catch (e) {}
      show();
    });
    show();
  });
})();
