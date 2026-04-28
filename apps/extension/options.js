const DEFAULT_API = "http://localhost:8000";

function setStatus(text) {
  document.getElementById("status").textContent = text;
}

document.addEventListener("DOMContentLoaded", () => {
  chrome.storage.sync.get(["apiBase"], (out) => {
    document.getElementById("apiBase").value = out?.apiBase || DEFAULT_API;
  });
  document.getElementById("save").addEventListener("click", () => {
    const v = document.getElementById("apiBase").value.trim() || DEFAULT_API;
    chrome.storage.sync.set({ apiBase: v }, () => {
      setStatus("Saved.");
      setTimeout(() => setStatus(""), 1500);
    });
  });
});
