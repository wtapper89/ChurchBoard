let moduleSettingsData=null;
let modulePositionTeams=[];
let moduleMicRows=[];
const moduleFallbackTimezones=["UTC","America/Anchorage","America/Chicago","America/Denver","America/Los_Angeles","America/New_York","America/Phoenix","Asia/Dubai","Asia/Jerusalem","Asia/Tokyo","Australia/Sydney","Europe/Berlin","Europe/London","Europe/Paris","Pacific/Auckland","Pacific/Honolulu"];

const settingAt=path=>path.split(".").reduce((value,key)=>value?.[key],moduleSettingsData);
function setSetting(path,value){const keys=path.split(".");let target=moduleSettingsData;keys.slice(0,-1).forEach(key=>target=target[key]??={});target[keys.at(-1)]=value}
const checked=path=>settingAt(path)?"checked":"";
const field=(label,path,options={})=>`<label>${escapeHtml(label)}${options.hint?` <span class="hint">${escapeHtml(options.hint)}</span>`:""}<input data-setting="${escapeHtml(path)}" type="${options.type||"text"}" ${options.type==="number"?`inputmode="numeric" ${options.min!=null?`min="${options.min}"`:""} ${options.max!=null?`max="${options.max}"`:""} ${options.step?`step="${options.step}"`:""}`:""} value="${options.secret?"":escapeHtml(settingAt(path)??options.fallback??"")}" ${options.placeholder?`placeholder="${escapeHtml(options.placeholder)}"`:""}></label>`;
const toggle=(label,path)=>`<label class="module-switch"><input data-setting="${escapeHtml(path)}" type="checkbox" ${checked(path)}><span aria-hidden="true"></span><strong>${escapeHtml(label)}</strong></label>`;
const selectField=(label,path,options)=>`<label>${escapeHtml(label)}<select data-setting="${escapeHtml(path)}">${options.map(([value,text])=>`<option value="${escapeHtml(value)}" ${String(settingAt(path)??"")===String(value)?"selected":""}>${escapeHtml(text)}</option>`).join("")}</select></label>`;

function browserTimezones(){try{return typeof Intl.supportedValuesOf==="function"?Intl.supportedValuesOf("timeZone"):[]}catch(error){return[]}}
function timezoneOptions(){const current=settingAt("timezone")||"America/New_York",zones=[...new Set(["UTC",...moduleFallbackTimezones,...browserTimezones(),current])].sort();return zones.map(zone=>`<option value="${escapeHtml(zone)}" ${zone===current?"selected":""}>${escapeHtml(zone.replaceAll("_"," "))}</option>`).join("")}

async function ensureModuleSettings(){
  if(moduleSettingsData)return moduleSettingsData;
  moduleSettingsData=await api("/api/settings");
  renderCoreSettings();
  return moduleSettingsData;
}

function renderCoreSettings(){
  const server=moduleSettingsData.server||{};
  const httpsReady=Boolean(server.https_enabled&&server.ssl_certfile&&server.ssl_keyfile);
  document.querySelector("#core-settings-fields").innerHTML=`
    <fieldset><legend>Church</legend>${field("Church name","organization_name")}<label>Timezone<select data-setting="timezone">${timezoneOptions()}</select></label>${toggle("Use demonstration data","demo_mode")}</fieldset>
    <fieldset><legend>Web server</legend><div class="module-form-columns">${field("Dashboard and setup port","server.port",{type:"number",min:1,max:65535,fallback:8040})}${field("Volunteer workspace port","server.producer_port",{type:"number",min:1,max:65535,fallback:80})}</div>${toggle("Use a separate volunteer workspace port","server.producer_port_enabled")}<div class="https-setup-card ${httpsReady?"ready":""}"><div><strong>${httpsReady?"HTTPS is configured":"Secure ChurchBoard with HTTPS"}</strong><p>${httpsReady?"ChurchBoard manages the local certificate automatically.":"Create and trust a certificate for this Mac. No certificate paths are required."}</p></div><button class="button ${httpsReady?"secondary":""}" type="button" data-setup-https>${httpsReady?"Renew certificate":"Set up HTTPS"}</button></div><p class="hint">Restart ChurchBoard after changing ports or setting up HTTPS. Phones and other computers must also trust ChurchBoard’s local certificate authority.</p></fieldset>`;
}

function collectSettings(root){
  root.querySelectorAll("[data-setting]").forEach(input=>{
    let value=input.type==="checkbox"?input.checked:input.value;
    if(input.type==="number")value=Number(value);
    setSetting(input.dataset.setting,value);
  });
  const partyLines=root.querySelector("[data-party-lines]");
  if(partyLines)setSetting("intercom.party_lines",partyLines.value.split("\n").map(name=>name.trim()).filter(Boolean).map((name,index)=>({id:name.toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"")||`line-${index+1}`,name})));
  const serviceTypes=root.querySelectorAll("[data-service-type]");
  if(serviceTypes.length)setSetting("planning_center.service_type_ids",[...serviceTypes].filter(input=>input.checked).map(input=>input.value));
}

function cleanSettingsPayload(){
  const payload=structuredClone(moduleSettingsData);
  for(const [section,names] of Object.entries({planning_center:["secret_configured"],prodmesh_rta:["engine_status"],restream:["client_secret_configured","access_token_configured"],obs:["password_configured"],lighting:["password_configured"],intercom:["api_key_configured","api_secret_configured","server_status","server_ports"]}))for(const name of names)delete payload[section]?.[name];
  return payload;
}

async function saveModuleSettings(root,status,message="Saved"){
  collectSettings(root);
  status.textContent="Saving…";
  moduleSettingsData=await api("/api/settings",{method:"PUT",body:JSON.stringify(cleanSettingsPayload())});
  status.textContent=message;
  renderCoreSettings();
  return moduleSettingsData;
}

function planningCenterMarkup(){
  const pc=moduleSettingsData.planning_center||{},selected=new Set((pc.service_type_ids||[]).map(String));
  const serviceTypes=(pc.service_types||[]).map(item=>`<label class="check"><input data-service-type type="checkbox" value="${escapeHtml(item.id)}" ${selected.has(String(item.id))?"checked":""}> ${escapeHtml(item.name)}</label>`).join("")||'<p class="hint">Save and test the connection to load service types.</p>';
  return `${toggle("Enable Planning Center","planning_center.enabled")}${field("Application ID","planning_center.application_id")}${field("Personal access token secret","planning_center.secret",{type:"password",secret:true,placeholder:"Leave blank to keep the saved secret"})}<div class="module-inline-actions"><button class="button secondary" type="button" data-module-test="planning-center">Save &amp; test connection</button><span class="hint">${pc.secret_configured?"Token saved":""}</span></div><h4>Service types ChurchBoard may activate</h4><div class="service-types">${serviceTypes}</div><div class="module-form-columns three">${field("Open days before","planning_center.open_days_before",{type:"number",min:0,max:30})}${field("Open hours before","planning_center.open_hours_before",{type:"number",min:0,max:48})}${field("Close hours after","planning_center.close_hours_after",{type:"number",min:0,max:48})}</div>`;
}

function moduleConfigurationMarkup(module){
  const id=module.id;
  if(id==="planning-center")return planningCenterMarkup();
  if(id==="propresenter")return `${toggle("Enable ProPresenter","propresenter.enabled")}<div class="module-form-columns">${field("Computer address","propresenter.host",{placeholder:"192.168.1.50"})}${field("Network API port","propresenter.port",{type:"number",min:1,max:65535})}</div><p class="hint">Enable Network in ProPresenter Settings. Slide-control permissions remain a page/widget choice.</p>`;
  if(id==="services-live-bridge")return `${toggle("Let ProPresenter drive Planning Center Services LIVE","planning_center.live_from_propresenter.enabled")}${toggle("Automatically take control when needed","planning_center.live_from_propresenter.auto_take_control")}${toggle("Prefer song items for title matching","planning_center.live_from_propresenter.songs_only")}${toggle("Allow moving LIVE backward","planning_center.live_from_propresenter.allow_previous")}<div class="module-form-columns">${selectField("Fallback title matching","planning_center.live_from_propresenter.match_mode",[["exact","Exact title"],["flexible","Smart title"]])}${field("Presentation stable for (seconds)","planning_center.live_from_propresenter.stable_seconds",{type:"number",min:0,max:30,step:"0.5"})}</div>`;
  if(["shure-wireless","sennheiser-wireless"].includes(id))return wirelessMarkup();
  if(id==="open-sound-meter")return `${toggle("Enable Open Sound Meter","open_sound_meter.enabled")}${toggle("Generate downloadable SPL reports","open_sound_meter.reports_enabled")}<div class="module-form-columns">${selectField("Report weighting","open_sound_meter.report_weighting",[...["A","B","C","Z"].map(value=>[value,`${value}-weighted`])])}${selectField("Report response","open_sound_meter.report_response",[["Fast","Fast"],["Slow","Slow"]])}</div>${field("Preferred measurement source ID","open_sound_meter.source_id",{hint:"optional"})}<div class="module-inline-actions"><button class="button secondary" type="button" data-module-test="osm">Save &amp; test OSM</button></div>`;
  if(id==="prodmesh-rta"){const status=moduleSettingsData.prodmesh_rta?.engine_status||{},embedded=String(moduleSettingsData.prodmesh_rta?.mode||"embedded")==="embedded";return `${toggle("Enable ProdMesh RTA","prodmesh_rta.enabled")}${toggle("Store per-service audio history in Producer","prodmesh_rta.reports_enabled")}${selectField("Where the analyzer runs","prodmesh_rta.mode",[["embedded","Inside ChurchBoard — no other installation"],["remote","Another ProdMesh computer"]])}<div class="module-form-columns"><label data-prodmesh-remote-host ${embedded?"hidden":""}>ProdMesh computer address<input data-setting="prodmesh_rta.host" value="${escapeHtml(settingAt("prodmesh_rta.host")||"")}" placeholder="192.168.1.75"></label>${field("Analyzer API port","prodmesh_rta.port",{type:"number",min:1,max:65535,fallback:8517})}</div><div class="module-inline-actions"><button class="button secondary" type="button" data-module-test="prodmesh">Save &amp; test</button><button class="button secondary" type="button" data-prodmesh-open ${embedded?"":"hidden"}>Open audio &amp; calibration settings</button><button class="button secondary" type="button" data-prodmesh-restart ${embedded?"":"hidden"}>Restart analyzer</button></div><p class="module-server-status">${embedded?escapeHtml(status.running?"Embedded analyzer is running":status.available?"Embedded analyzer will start when enabled":status.error||"Embedded analyzer is included with packaged ChurchBoard builds"):"ChurchBoard will connect to the ProdMesh API on another computer."}</p><p class="hint">Embedded mode includes and supervises ProdMesh Remote RTA. On first use, allow microphone access and select the input or interface channel in its audio settings.</p>`;}
  if(id==="showxpress-lighting")return `${toggle("Enable ShowXpress / TLC control","lighting.enabled")}<div class="module-form-columns">${field("Lighting computer address","lighting.host",{placeholder:"192.168.1.80"})}${field("External App port","lighting.port",{type:"number",min:1,max:65535,fallback:7348})}</div>${field("External App password","lighting.password",{type:"password",secret:true,placeholder:"Leave blank to keep the saved password"})}<div class="module-inline-actions"><button class="button secondary" type="button" data-module-test="lighting">Save &amp; read buttons</button></div>`;
  if(id==="restream")return `${toggle("Enable Restream monitoring","restream.enabled")}${field("Client ID","restream.client_id")}${field("Client Secret","restream.client_secret",{type:"password",secret:true,placeholder:"Leave blank to keep the saved secret"})}<p class="hint">OAuth callback: <code>${escapeHtml(location.origin)}/api/integrations/restream/callback</code></p><div class="module-inline-actions"><button class="button secondary" type="button" data-module-test="restream">Save &amp; test</button><button class="button secondary" type="button" data-module-connect="restream">Save &amp; connect account</button></div>`;
  if(id==="obs-studio")return `${toggle("Enable OBS Studio monitoring","obs.enabled")}<div class="module-form-columns">${field("Computer address","obs.host",{placeholder:"127.0.0.1"})}${field("WebSocket port","obs.port",{type:"number",min:1,max:65535})}</div>${field("WebSocket password","obs.password",{type:"password",secret:true,placeholder:"Leave blank to keep the saved password"})}${field("Dropped-frame warning threshold (%)","obs.dropped_frames_threshold",{type:"number",min:0,max:100,step:"0.1"})}${field("Optional preview image URL","obs.preview_url",{type:"url"})}`;
  if(id==="ndi-video")return `${toggle("Enable NDI source discovery and previews","ndi.enabled")}${field("NDI SDK or runtime location","ndi.runtime_directory",{hint:"optional — standard folders are detected automatically"})}<div class="module-inline-actions"><button class="button secondary" type="button" data-module-test="ndi">Save &amp; find NDI sources</button></div><p class="hint"><a href="https://ndi.video/for-developers/ndi-sdk/download/" target="_blank" rel="noreferrer">Download the official NDI SDK</a>, install it in the default folder, restart ChurchBoard, then run the source check.</p>`;
  if(id==="producer-intercom"){const intercom=moduleSettingsData.intercom||{},ports=intercom.server_ports||{};return `${toggle("Enable the ChurchBoard-hosted intercom","intercom.enabled")}<label>Party lines <span class="hint">one name per line</span><textarea data-party-lines rows="5">${escapeHtml((intercom.party_lines||[{name:"Production"}]).map(line=>line.name).join("\n"))}</textarea></label><p class="module-server-status">${escapeHtml(intercom.server_status||"ChurchBoard starts the audio engine after you save.")}</p><p class="hint">Default ports are signaling 7880, TCP 7881, and UDP 7882. If another application is using them, ChurchBoard automatically selects a free set${ports.signal?` (currently ${ports.signal}/${ports.tcp}/${ports.udp})`:""}.</p>`}
  if(id==="producer")return '<p>Accounts, roles, checklists, resources, and campuses are managed in the Producer workspace.</p><a class="button secondary" href="/producer">Open Producer</a>';
  if(id==="livestream-monitor")return '<p>Each page can monitor different destinations. Configure Facebook, YouTube, BoxCast, Resi, or Restream from the Livestream Status widget in that page’s editor.</p><a class="button secondary" href="/desktop">Choose a board</a>';
  if(id==="churchboard-core")return '<p>Core page layout settings are managed per board. Church and server settings remain at the top of this setup page.</p><a class="button secondary" href="/desktop">Manage boards</a>';
  return '<p class="muted">This module has no global settings. Its options are configured on the page or widget where it is used.</p>';
}

function hydrateModuleMics(){
  const shure=moduleSettingsData.shure||{},sennheiser=moduleSettingsData.sennheiser||{};
  moduleMicRows=[...(shure.mics||[]).map(mic=>({...mic,manufacturer:String(mic.model||"").toLowerCase()==="slxd"?"shure-slxd":"shure"})),...(sennheiser.mics||[]).map(mic=>({...mic,manufacturer:"sennheiser"}))];
}
function modulePositionOptions(selected=""){return '<option value="">Unassigned</option>'+modulePositionTeams.map(team=>`<optgroup label="${escapeHtml(team.name)}">${(team.positions||[]).map(position=>`<option value="${escapeHtml(position.key)}" ${position.key===selected?"selected":""}>${escapeHtml(position.name)}</option>`).join("")}</optgroup>`).join("")}
function wirelessMarkup(){hydrateModuleMics();return `${toggle("Enable Shure QLX-D / ULX-D / SLX-D","shure.enabled")}${toggle("Enable Sennheiser EW-DX","sennheiser.enabled")}<div class="module-inline-actions"><button class="button secondary" type="button" data-add-module-mic>＋ Add microphone</button></div><div class="module-mic-manager">${moduleMicRows.map(moduleMicMarkup).join("")||'<div class="empty-row"><strong>No microphones configured</strong><span>Add a receiver channel when you are ready.</span></div>'}</div>`}
function moduleMicMarkup(mic){return `<div class="module-mic-row" data-module-mic="${escapeHtml(mic.id)}"><label>Name<input data-mic-field="name" value="${escapeHtml(mic.name||"")}" placeholder="Red"></label><label>Receiver<select data-mic-field="manufacturer"><option value="shure" ${mic.manufacturer==="shure"?"selected":""}>Shure QLX-D / ULX-D</option><option value="shure-slxd" ${mic.manufacturer==="shure-slxd"?"selected":""}>Shure SLX-D</option><option value="sennheiser" ${mic.manufacturer==="sennheiser"?"selected":""}>Sennheiser EW-DX</option></select></label><label>IP address<input data-mic-field="host" value="${escapeHtml(mic.host||"")}" placeholder="192.168.1.60"></label><label>Channel<input data-mic-field="channel" type="number" min="1" max="8" value="${Number(mic.channel)||1}"></label><label>Planning Center position<select data-mic-field="position_key">${modulePositionOptions(mic.position_key||"")}</select></label><button class="icon-button danger" type="button" data-delete-module-mic aria-label="Delete microphone">×</button></div>`}

function collectWireless(){
  const ids=new Set();
  for(const mic of moduleMicRows){if(!String(mic.name||"").trim()||!String(mic.host||"").trim())throw new Error("Every microphone needs a name and receiver IP address");const key=`${mic.manufacturer}:${mic.host}:${mic.channel}`;if(ids.has(key))throw new Error(`Receiver ${mic.host} channel ${mic.channel} is listed more than once`);ids.add(key)}
  const map={};moduleMicRows.forEach(mic=>{if(mic.position_key)map[mic.position_key]=mic.id});moduleSettingsData.position_mic_map=map;
  moduleSettingsData.shure={...(moduleSettingsData.shure||{}),receivers:[],mics:moduleMicRows.filter(mic=>mic.manufacturer!=="sennheiser").map(({manufacturer,...mic})=>({...mic,port:2202,channel:Number(mic.channel)||1,model:manufacturer==="shure-slxd"?"slxd":"qlx-ulx"}))};
  moduleSettingsData.sennheiser={...(moduleSettingsData.sennheiser||{}),receivers:[],mics:moduleMicRows.filter(mic=>mic.manufacturer==="sennheiser").map(({manufacturer,...mic})=>({...mic,port:45,channel:Number(mic.channel)||1}))};
}

async function openModuleSettings(module){
  await ensureModuleSettings();
  if(["shure-wireless","sennheiser-wireless"].includes(module.id))try{modulePositionTeams=(await api("/api/integrations/planning-center/catalog")).items||[]}catch(error){modulePositionTeams=[]}
  const root=document.querySelector("#module-configuration"),status=document.querySelector("#module-configuration-status");status.textContent="";root.innerHTML=`<div class="module-config-form" data-config-module="${escapeHtml(module.id)}">${moduleConfigurationMarkup(module)}${!["producer","livestream-monitor","churchboard-core"].includes(module.id)?'<div class="module-config-save"><button class="button" type="button" data-save-module-settings>Save module settings</button></div>':""}</div>`;
}

document.querySelector("#core-settings-fields").addEventListener("click",async event=>{if(!event.target.closest("[data-setup-https]"))return;const button=event.target.closest("[data-setup-https]"),status=document.querySelector("#core-settings-status");button.disabled=true;button.textContent="Setting up…";status.textContent="Creating and trusting a certificate for your Mac account…";try{const result=await api("/api/settings/https/setup",{method:"POST"});moduleSettingsData=result.settings;renderCoreSettings();status.textContent=result.message}catch(error){status.textContent=error.message;button.disabled=false;button.textContent="Try again"}});
document.querySelector("#core-settings-save").addEventListener("click",async()=>{const status=document.querySelector("#core-settings-status");try{await ensureModuleSettings();await saveModuleSettings(document.querySelector("#core-settings-fields"),status,"Core settings saved. Restart ChurchBoard if you changed server options.")}catch(error){status.textContent=error.message}});
document.querySelector("#module-configuration").addEventListener("input",event=>{const row=event.target.closest("[data-module-mic]"),field=event.target.dataset.micField;if(!row||!field)return;const mic=moduleMicRows.find(item=>item.id===row.dataset.moduleMic);if(mic)mic[field]=field==="channel"?Number(event.target.value)||1:event.target.value});
document.querySelector("#module-configuration").addEventListener("change",event=>{if(event.target.dataset.setting!=="prodmesh_rta.mode")return;collectSettings(event.currentTarget);openModuleSettings({id:"prodmesh-rta"})});
document.querySelector("#module-configuration").addEventListener("click",async event=>{
  const root=event.currentTarget,status=document.querySelector("#module-configuration-status"),form=root.querySelector("[data-config-module]");
  if(event.target.closest("[data-add-module-mic]")){const mic={id:`mic-${Date.now().toString(36)}`,name:`Mic ${moduleMicRows.length+1}`,manufacturer:"shure",host:"",port:2202,channel:1,position_key:""};moduleMicRows.push(mic);const manager=root.querySelector(".module-mic-manager");if(manager.querySelector(".empty-row"))manager.innerHTML="";manager.insertAdjacentHTML("beforeend",moduleMicMarkup(mic));return}
  const deleteButton=event.target.closest("[data-delete-module-mic]");if(deleteButton){moduleMicRows=moduleMicRows.filter(mic=>mic.id!==deleteButton.closest("[data-module-mic]").dataset.moduleMic);deleteButton.closest("[data-module-mic]").remove();return}
  try{
    if(event.target.closest("[data-save-module-settings]")){collectSettings(root);if(["shure-wireless","sennheiser-wireless"].includes(form.dataset.configModule))collectWireless();await saveModuleSettings(root,status,"Module settings saved.");await openModuleSettings({id:form.dataset.configModule});status.textContent="Module settings saved.";return}
    if(event.target.closest("[data-prodmesh-open]")){await saveModuleSettings(root,status,"Opening analyzer settings…");const result=await api("/api/integrations/prodmesh-rta/open",{method:"POST"});status.textContent=result.message;return}
    if(event.target.closest("[data-prodmesh-restart]")){await saveModuleSettings(root,status,"Restarting analyzer…");const result=await api("/api/integrations/prodmesh-rta/restart",{method:"POST"});status.textContent=result.message;return}
    const test=event.target.closest("[data-module-test]");if(test){collectSettings(root);if(["shure-wireless","sennheiser-wireless"].includes(form.dataset.configModule))collectWireless();await saveModuleSettings(root,status,"Testing…");const paths={"planning-center":"/api/integrations/planning-center/test",osm:"/api/integrations/osm/test",prodmesh:"/api/integrations/prodmesh-rta/test",lighting:"/api/integrations/lighting/buttons",restream:"/api/integrations/restream/test",ndi:"/api/integrations/ndi/sources"},result=await api(paths[test.dataset.moduleTest],{method:["ndi","lighting"].includes(test.dataset.moduleTest)?"GET":"POST"});if(test.dataset.moduleTest==="planning-center"){moduleSettingsData.planning_center.service_types=result.items||[];await saveModuleSettings(root,status,"Connection ready.");await openModuleSettings({id:"planning-center"})}status.textContent=result.message||`${result.count??result.items?.length??0} item${(result.count??result.items?.length)!==1?"s":""} found`;return}
    if(event.target.closest("[data-module-connect=restream]")){await saveModuleSettings(root,status,"Opening Restream…");location.href="/api/integrations/restream/connect"}
  }catch(error){status.textContent=error.message}
});

window.ModuleSettings={open:openModuleSettings,ready:ensureModuleSettings};
ensureModuleSettings().catch(error=>{document.querySelector("#core-settings-status").textContent=error.message});
