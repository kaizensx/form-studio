// Light and dark: follows the system until the visitor picks one; the choice is kept in this browser only.
export function initTheme(btn) {
  if (!btn) return;
  const root = document.documentElement;
  const sys = () => (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  const now = () => root.dataset.theme || sys();
  const label = () => btn.setAttribute("aria-label", now() === "light" ? "Switch to the dark theme" : "Switch to the light theme");
  label();
  btn.addEventListener("click", () => {
    const next = now() === "light" ? "dark" : "light";
    root.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch { /* private mode: the choice lasts for this page */ }
    label();
  });
}
