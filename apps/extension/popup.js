// MV3 popup. On load, hydrates the form from the active tab via a one-shot
// scripting.executeScript. On save, POSTs to the configured Job Search Pal
// API. Auth: relies on the user already being signed in to the API in
// their default browser profile (cookies are sent via credentials: include).

const DEFAULT_API = "http://localhost:8000";

async function getApiBase() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(["apiBase"], (out) => {
      resolve((out?.apiBase || DEFAULT_API).replace(/\/+$/, ""));
    });
  });
}

function setStatus(text, kind) {
  const el = document.getElementById("status");
  el.textContent = text;
  el.className = kind || "";
}

// Best-effort title/org/location extraction from common job-board patterns.
// Runs in the page context. The user can correct anything in the popup
// before hitting Save — this is a head start, not ground truth.
function extractFromPage() {
  function pick(selectors) {
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el && el.textContent && el.textContent.trim()) {
        return el.textContent.trim();
      }
    }
    return "";
  }
  const title = pick([
    "h1[data-test='job-title']",
    "h1.jobTitle",
    "h1.posting-headline",
    "h1.t-24",
    "h1",
  ]);
  const org = pick([
    "[data-test='employer-name']",
    "a[href*='/company/']",
    "[itemprop='hiringOrganization']",
    ".topcard__org-name-link",
  ]);
  const location = pick([
    "[data-test='location']",
    "[itemprop='jobLocation']",
    ".topcard__flavor--bullet",
    ".jobLocation",
  ]);
  // Body text — use the largest <article> / <main> / <section> the page
  // exposes, falling back to body.innerText. Truncate to keep popup
  // responsive; the API will further normalize on save.
  const candidates = ["article", "main", "[role='main']"];
  let body = "";
  for (const sel of candidates) {
    const el = document.querySelector(sel);
    if (el && el.innerText && el.innerText.length > body.length) {
      body = el.innerText;
    }
  }
  if (!body) body = document.body.innerText || "";
  body = body.replace(/\s+\n/g, "\n").replace(/\n{3,}/g, "\n\n").slice(0, 12000);
  return {
    title,
    organization: org,
    location,
    url: window.location.href,
    body,
  };
}

async function hydrate() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) {
    setStatus("No active tab.", "err");
    return;
  }
  document.getElementById("url").value = tab.url || "";
  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: extractFromPage,
    });
    if (result) {
      document.getElementById("title").value = result.title || tab.title || "";
      document.getElementById("org").value = result.organization || "";
      document.getElementById("location").value = result.location || "";
      document.getElementById("jd").value = result.body || "";
    }
  } catch (e) {
    document.getElementById("title").value = tab.title || "";
    setStatus(
      "Couldn't read this tab. The page may block extensions.",
      "err",
    );
  }
}

async function save() {
  const btn = document.getElementById("save");
  btn.disabled = true;
  setStatus("Saving…");
  try {
    const apiBase = await getApiBase();
    const payload = {
      title: document.getElementById("title").value.trim(),
      source_url: document.getElementById("url").value.trim() || null,
      location: document.getElementById("location").value.trim() || null,
      job_description: document.getElementById("jd").value.trim() || null,
      status: "to_review",
    };
    const orgName = document.getElementById("org").value.trim();
    if (!payload.title) {
      setStatus("Title is required.", "err");
      return;
    }
    // The API expects organization_id, not a name. Skip org for now —
    // user can attach it on the tracker. Notes carry the raw name so
    // it isn't lost.
    if (orgName) {
      payload.notes = `Captured organization: ${orgName}`;
    }
    const res = await fetch(`${apiBase}/api/v1/jobs`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(`HTTP ${res.status}: ${txt.slice(0, 200)}`);
    }
    const out = await res.json();
    setStatus(`Saved as job #${out.id}. Open it in the tracker.`, "ok");
    // Open the tracker page after a beat so the user sees the success line.
    setTimeout(() => {
      chrome.tabs.create({ url: `${apiBase.replace(":8000", ":3000")}/jobs/${out.id}` });
    }, 700);
  } catch (e) {
    setStatus(
      `Save failed: ${e?.message || e}. Are you signed in at ${await getApiBase()}?`,
      "err",
    );
  } finally {
    btn.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("save").addEventListener("click", save);
  document.getElementById("open-options").addEventListener("click", () => {
    chrome.runtime.openOptionsPage();
  });
  hydrate();
});
