(() => {
  async function devices() {
    const response = await fetch("/api/integrations/webcam/devices", {cache: "no-store"});
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "Could not find USB cameras");
    return payload.items || [];
  }

  function enhance(root = document) {
    root.querySelectorAll("[data-webcam-preview]").forEach(image => {
      if (image.dataset.webcamAttached === "true") return;
      image.dataset.webcamAttached = "true";
      const status = image.parentElement?.querySelector("[data-webcam-status]");
      image.addEventListener("load", () => { if (status) status.hidden = true; }, {once: true});
      image.addEventListener("error", () => {
        image.dataset.webcamAttached = "false";
        if (status) {
          status.hidden = false;
          status.textContent = "Camera unavailable · check its connection and macOS camera permission";
        }
      }, {once: true});
      image.src = `/api/integrations/webcam/stream/${encodeURIComponent(image.dataset.webcamDevice)}`;
    });
  }

  const messageFor = error => error?.message || "Camera preview unavailable";
  window.ChurchBoardWebcams = {devices, enhance, messageFor};
})();
