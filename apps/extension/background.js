// MV3 service worker — currently a no-op. Reserved for: context-menu
// "Save selection as a writing sample", omnibox commands, or
// notifications when async tailor jobs finish on the API side.

chrome.runtime.onInstalled.addListener(() => {
  // First-install nudge — open the options page so the user sets the
  // API base URL if it isn't already set.
  chrome.storage.sync.get(["apiBase"], (out) => {
    if (!out?.apiBase) {
      chrome.runtime.openOptionsPage();
    }
  });
});
