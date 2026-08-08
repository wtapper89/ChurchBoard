const boards = document.querySelector("#desktop-boards");
const version = document.querySelector("#desktop-version");
const updateStatus = document.querySelector("#update-status");
const updateActions = document.querySelector("#update-actions");
const installUpdate = document.querySelector("#install-update");
const releaseLink = document.querySelector("#release-link");

async function loadDesktop() {
  try {
    const [appResponse, boardsResponse] = await Promise.all([fetch("/api/app-info"), fetch("/api/dashboards")]);
    const info = await appResponse.json();
    const data = await boardsResponse.json();
    version.textContent = info.version;
    boards.innerHTML = data.items.map(board => `
      <a class="desktop-board" href="/display/${encodeURIComponent(board.slug)}">
        <img src="/static/churchboard-icon.png" alt="">
        <span>${escapeHtml(board.name)}<small>Open display</small></span>
      </a>`).join("") || '<p class="muted">No boards are configured yet.</p>';
  } catch (error) {
    boards.innerHTML = '<p class="muted">ChurchBoard could not load the board list.</p>';
  }
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, character => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[character]);
}

async function checkForUpdates() {
  const button = document.querySelector("#check-update");
  button.disabled = true;
  button.textContent = "Checking…";
  updateStatus.textContent = "Checking GitHub for a newer ChurchBoard release…";
  updateActions.hidden = true;
  try {
    const response = await fetch("/api/desktop/update");
    const data = await response.json();
    updateStatus.textContent = data.message;
    releaseLink.href = data.release_url;
    updateActions.hidden = !(data.available || data.requires_auth || !data.latest_version);
    installUpdate.hidden = !data.can_install;
  } catch (error) {
    updateStatus.textContent = "ChurchBoard could not check for updates right now.";
    updateActions.hidden = false;
    installUpdate.hidden = true;
  } finally {
    button.disabled = false;
    button.textContent = "Check for updates";
  }
}

document.querySelector("#check-update").addEventListener("click", checkForUpdates);
installUpdate.addEventListener("click", async () => {
  installUpdate.disabled = true;
  installUpdate.textContent = "Downloading…";
  updateStatus.textContent = "Downloading the installer from GitHub…";
  try {
    const response = await fetch("/api/desktop/update", {method: "POST"});
    const data = await response.json();
    updateStatus.textContent = data.message;
  } catch (error) {
    updateStatus.textContent = "The installer could not be downloaded. Open GitHub releases to update manually.";
  } finally {
    installUpdate.disabled = false;
    installUpdate.textContent = "Download and install update";
  }
});

document.querySelector("#quit-app").addEventListener("click", async () => {
  if (!confirm("Quit ChurchBoard? Your displays will stop updating until ChurchBoard is started again.")) return;
  const response = await fetch("/api/desktop/quit", {method: "POST"});
  if (response.ok) {
    document.body.innerHTML = '<main class="desktop-shell"><section class="desktop-section"><h1>ChurchBoard has stopped.</h1><p class="muted">You can close this browser window. Start ChurchBoard again from Applications or the Start menu.</p></section></main>';
  } else {
    const data = await response.json();
    alert(data.detail || "ChurchBoard could not be stopped from this window.");
  }
});

loadDesktop();
if (location.hash === "#updates") checkForUpdates();
document.querySelector("#layout-import").addEventListener("change",async event=>{const file=event.target.files[0],status=document.querySelector("#layout-import-status");if(!file)return;status.textContent="Importing layouts…";try{const response=await fetch("/api/layouts/import",{method:"POST",headers:{"Content-Type":"application/json"},body:await file.text()}),data=await response.json();if(!response.ok)throw new Error(data.detail||"Import failed");status.textContent=`Imported ${data.count} layout${data.count===1?"":"s"}.`;await loadDesktop()}catch(error){status.textContent=error.message}finally{event.target.value=""}});
