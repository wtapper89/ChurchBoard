let settings,micRows=[],positionTeams=[],serviceTypeRows=[];
const cards=document.querySelector("#dashboard-cards"),sf=document.querySelector("#settings-form");
const micId=()=>`mic-${Date.now().toString(36)}-${Math.random().toString(36).slice(2,7)}`;
const fallbackTimezones=["UTC","America/Anchorage","America/Chicago","America/Denver","America/Halifax","America/Los_Angeles","America/New_York","America/Phoenix","America/St_Johns","America/Toronto","Asia/Dubai","Asia/Hong_Kong","Asia/Jerusalem","Asia/Kolkata","Asia/Seoul","Asia/Shanghai","Asia/Singapore","Asia/Tokyo","Australia/Adelaide","Australia/Brisbane","Australia/Darwin","Australia/Hobart","Australia/Melbourne","Australia/Perth","Australia/Sydney","Europe/Amsterdam","Europe/Berlin","Europe/Lisbon","Europe/London","Europe/Madrid","Europe/Paris","Europe/Rome","Pacific/Auckland","Pacific/Honolulu"];

function browserTimezones(){
  try{return typeof Intl.supportedValuesOf==="function"?Intl.supportedValuesOf("timeZone"):[]}catch(error){return[]}
}

function renderTimezoneOptions(items,current){
  const select=sf.timezone,zones=[...new Set(["UTC",...items,...browserTimezones(),current].filter(Boolean))].sort((a,b)=>a.localeCompare(b));
  select.replaceChildren();
  const groups=new Map();
  zones.forEach(zone=>{const [region,...place]=zone.split("/"),group=place.length?region:"General",label=(place.length?place.join(" / "):region).replaceAll("_"," ");if(!groups.has(group))groups.set(group,[]);groups.get(group).push({zone,label})});
  [...groups].sort(([a],[b])=>a.localeCompare(b)).forEach(([region,options])=>{const group=document.createElement("optgroup");group.label=region.replaceAll("_"," ");options.forEach(({zone,label})=>{const option=document.createElement("option");option.value=zone;option.textContent=label;group.append(option)});select.append(group)});
  select.value=current||"America/New_York";
}

async function loadTimezoneOptions(current){
  let items=[];
  try{items=(await api("/api/timezones")).items||[]}catch(error){items=fallbackTimezones}
  renderTimezoneOptions(items.length?items:fallbackTimezones,current);
}

async function loadDashboards(){
  const data=await api("/api/dashboards");
  cards.innerHTML=data.items.map(item=>`<article class="dashboard-card"><h3>${escapeHtml(item.name)}</h3><p>/display/${escapeHtml(item.slug)} · ${item.widgets.length} widgets</p><div class="card-actions"><a class="button" href="/editor/${encodeURIComponent(item.slug)}">Edit</a><a class="button secondary" href="/display/${encodeURIComponent(item.slug)}" target="_blank">Display</a></div></article>`).join("");
}

function renderServiceTypes(items=serviceTypeRows){
  const selected=new Set(((settings.planning_center||{}).service_type_ids||[]).map(String)),root=document.querySelector("#pc-service-types");
  const rows=[...items,...[...selected].filter(id=>!items.some(item=>String(item.id)===String(id))).map(id=>({id,name:`Service type ${id}`}))];
  if(!rows.length){
    root.innerHTML='<p class="hint">Test the connection to choose which service types ChurchBoard may activate.</p>';
    return;
  }
  root.innerHTML=rows.map(item=>`<label class="check"><input type="checkbox" data-service-type value="${escapeHtml(item.id)}" ${selected.has(String(item.id))?"checked":""}> ${escapeHtml(item.name)}</label>`).join("");
}

function positionOptions(selected=""){
  const empty=`<option value="">Unassigned</option>`;
  return empty+positionTeams.map(team=>`<optgroup label="${escapeHtml(team.name)}">${(team.positions||[]).map(position=>`<option value="${escapeHtml(position.key)}" ${position.key===selected?"selected":""}>${escapeHtml(position.name)}</option>`).join("")}</optgroup>`).join("");
}

function hydrateMics(shure,sennheiser){
  const configured=[...(shure.mics||[]).map(mic=>({...mic,manufacturer:String(mic.model||"").toLowerCase()==="slxd"?"shure-slxd":"shure",channel:Number(mic.channel)||1,port:Number(mic.port)||2202})),...(sennheiser.mics||[]).map(mic=>({...mic,manufacturer:"sennheiser",channel:Number(mic.channel)||1,port:Number(mic.port)||45}))];
  if(configured.length){micRows=configured;return}
  const mapped=Object.fromEntries(Object.entries(settings.position_mic_map||{}).map(([position,id])=>[id,position]));
  micRows=(shure.receivers||[]).flatMap(receiver=>Array.from({length:Number(receiver.channels)||2},(_,offset)=>{const channel=offset+1,id=`${receiver.id||receiver.host}-${channel}`;return{id,name:`${receiver.name||"Mic"} ${channel}`,host:receiver.host||"",port:Number(receiver.port)||2202,channel,position_key:mapped[id]||""}}));
}

function renderMicManager(){
  const root=document.querySelector("#mic-manager"),status=document.querySelector("#mic-manager-status");
  root.innerHTML=micRows.map(mic=>`<div class="mic-manager-row" data-mic-id="${escapeHtml(mic.id)}"><label data-label="Mic name"><input data-mic-field="name" value="${escapeHtml(mic.name||"")}" placeholder="Blue"></label><label data-label="Receiver family"><select data-mic-field="manufacturer"><option value="shure" ${mic.manufacturer==="shure"?"selected":""}>Shure QLX-D / ULX-D</option><option value="shure-slxd" ${mic.manufacturer==="shure-slxd"?"selected":""}>Shure SLX-D</option><option value="sennheiser" ${mic.manufacturer==="sennheiser"?"selected":""}>Sennheiser EW-DX</option></select></label><label data-label="Receiver IP"><input data-mic-field="host" value="${escapeHtml(mic.host||"")}" inputmode="decimal" placeholder="192.168.1.60"></label><label data-label="Channel"><input data-mic-field="channel" value="${Number(mic.channel)||1}" type="number" min="1" max="8"></label><label data-label="Position"><select data-mic-field="position_key">${positionOptions(mic.position_key||"")}</select></label><button class="icon-button danger" type="button" data-delete-mic aria-label="Delete ${escapeHtml(mic.name||"microphone")}">×</button></div>`).join("")||`<div class="empty-row"><strong>No microphones configured</strong><span>Choose “Add microphone” to connect a Shure or Sennheiser channel.</span></div>`;
  status.textContent=!positionTeams.length?"Connect Planning Center to assign scheduled positions. You can still configure mic names and IP addresses now.":`${micRows.length} microphone${micRows.length===1?"":"s"} configured`;
}

async function loadPositionCatalog(){
  try{positionTeams=(await api("/api/integrations/planning-center/catalog")).items||[];const known=new Map(serviceTypeRows.map(item=>[String(item.id),item]));positionTeams.forEach(team=>known.set(String(team.service_type_id),{id:String(team.service_type_id),name:team.service_type_name}));serviceTypeRows=[...known.values()];renderServiceTypes()}catch(error){positionTeams=[]}
  renderMicManager();
}

async function loadSettings(){
  settings=await api("/api/settings");
  const pc=settings.planning_center||{},pp=settings.propresenter||{},sh=settings.shure||{},se=settings.sennheiser||{},osm=settings.open_sound_meter||{},restream=settings.restream||{},obs=settings.obs||{},ndi=settings.ndi||{},intercom=settings.intercom||{},server=settings.server||{},live=pc.live_from_propresenter||{};
  serviceTypeRows=pc.service_types||[];
  try{const runtime=await api("/api/runtime"),service=runtime.service||{},id=String(service.service_type_id||""),liveStatus=runtime.planning_center_live||{};if(id&&service.service_type_name&&!serviceTypeRows.some(item=>String(item.id)===id))serviceTypeRows.push({id,name:service.service_type_name});document.querySelector("#pp-live-status").textContent=liveStatus.message||""}catch(error){}
  sf.organization_name.value=settings.organization_name||"";await loadTimezoneOptions(settings.timezone||"America/New_York");sf.demo_mode.checked=!!settings.demo_mode;document.querySelector("#restream-callback-url").textContent=`${location.origin}/api/integrations/restream/callback`;
  sf.server_port.value=Number(server.port)||8040;sf.producer_port_enabled.checked=server.producer_port_enabled!==false;sf.producer_port.value=Number(server.producer_port)||80;sf.https_enabled.checked=!!server.https_enabled;sf.ssl_certfile.value=server.ssl_certfile||"";sf.ssl_keyfile.value=server.ssl_keyfile||"";
  sf.ndi_enabled.checked=!!ndi.enabled;sf.ndi_runtime_directory.value=ndi.runtime_directory||"";
  sf.intercom_enabled.checked=!!intercom.enabled;sf.intercom_party_lines.value=(intercom.party_lines||[{name:"Production"}]).map(row=>row.name).join("\n");document.querySelector("#intercom-server-status").textContent=intercom.server_status||"ChurchBoard starts and manages the intercom server automatically.";
  sf.pc_enabled.checked=!!pc.enabled;sf.pc_application_id.value=pc.application_id||"";sf.pc_days.value=pc.open_days_before??2;sf.pc_hours.value=pc.open_hours_before??3;sf.pc_close.value=pc.close_hours_after??3;
  sf.pp_enabled.checked=!!pp.enabled;sf.pp_host.value=pp.host||"127.0.0.1";sf.pp_port.value=pp.port||50001;sf.shure_enabled.checked=!!sh.enabled;sf.osm_enabled.checked=!!osm.enabled;sf.osm_reports_enabled.checked=osm.reports_enabled!==false;sf.osm_report_weighting.value=osm.report_weighting||"A";sf.osm_report_response.value=osm.report_response||"Fast";try{const runtime=await api("/api/runtime"),latest=runtime.osm||{},sources=latest.sources||[];sf.osm_source_id.innerHTML='<option value="">First detected source</option>'+sources.map(source=>`<option value="${escapeHtml(source.id)}">${escapeHtml(source.name)}${source.host?` · ${escapeHtml(source.host)}`:""}${Number.isFinite(Number(source.level))?` · ${Number(source.level).toFixed(1)} dB`:""}</option>`).join("");sf.osm_source_id.value=osm.source_id||"";document.querySelector("#osm-status").textContent=latest.connected?`Connected to ${latest.source_name||"OSM source"} · A Fast ${Number(latest.a_fast||latest.laeq).toFixed(1)} dB`:"Waiting for OSM multicast data."}catch(error){}
  sf.restream_enabled.checked=!!restream.enabled;sf.restream_client_id.value=restream.client_id||"";document.querySelector("#restream-status").textContent=restream.access_token_configured?"Restream account connected":restream.client_secret_configured?"Client Secret saved; connect the account":"";
  sf.obs_enabled.checked=!!obs.enabled;sf.obs_host.value=obs.host||"127.0.0.1";sf.obs_port.value=obs.port||4455;sf.obs_dropped_frames_threshold.value=Number(obs.dropped_frames_threshold??2);sf.obs_preview_url.value=obs.preview_url||"";
  sf.pp_live_enabled.checked=!!live.enabled;sf.pp_live_take_control.checked=live.auto_take_control!==false;sf.pp_live_songs_only.checked=live.songs_only!==false;sf.pp_live_allow_previous.checked=!!live.allow_previous;sf.pp_live_match_mode.value=live.match_mode||"exact";sf.pp_live_stable_seconds.value=Number(live.stable_seconds??2);
  document.querySelector("#pc-status").textContent=pc.secret_configured?"Token saved; connection not yet tested":"";
  sf.sennheiser_enabled.checked=!!se.enabled;renderServiceTypes();hydrateMics(sh,se);await loadPositionCatalog();
}

function settingsPayload(){
  const missing=micRows.find(mic=>!String(mic.name||"").trim()||!String(mic.host||"").trim());if(missing)throw new Error("Every microphone needs a name and receiver IP address");
  const endpoints=new Set();for(const mic of micRows){const key=`${mic.manufacturer||"shure"}:${mic.host}:${Number(mic.channel)||1}`;if(endpoints.has(key))throw new Error(`Receiver ${mic.host} channel ${mic.channel} is listed more than once`);endpoints.add(key)}
  const micMap={};micRows.forEach(mic=>{if(mic.position_key)micMap[mic.position_key]=mic.id});
  const pcBase={...(settings.planning_center||{})};delete pcBase.secret_configured;
  const serviceTypeIds=[...document.querySelectorAll("[data-service-type]:checked")].map(input=>input.value);
  return {...settings,organization_name:sf.organization_name.value,timezone:sf.timezone.value,demo_mode:sf.demo_mode.checked,
    planning_center:{...pcBase,enabled:sf.pc_enabled.checked,application_id:sf.pc_application_id.value,secret:sf.pc_secret.value,service_type_ids:serviceTypeIds,service_types:serviceTypeRows,open_days_before:Number(sf.pc_days.value),open_hours_before:Number(sf.pc_hours.value),close_hours_after:Number(sf.pc_close.value),live_from_propresenter:{...(pcBase.live_from_propresenter||{}),enabled:sf.pp_live_enabled.checked,auto_take_control:sf.pp_live_take_control.checked,songs_only:sf.pp_live_songs_only.checked,allow_previous:sf.pp_live_allow_previous.checked,match_mode:sf.pp_live_match_mode.value,stable_seconds:Math.max(0,Number(sf.pp_live_stable_seconds.value)||0)}},
    propresenter:{...(settings.propresenter||{}),enabled:sf.pp_enabled.checked,host:sf.pp_host.value,port:Number(sf.pp_port.value)},
    server:{port:Math.max(1,Math.min(65535,Number(sf.server_port.value)||8040)),producer_port_enabled:sf.producer_port_enabled.checked,producer_port:Math.max(1,Math.min(65535,Number(sf.producer_port.value)||80)),https_enabled:sf.https_enabled.checked,ssl_certfile:sf.ssl_certfile.value.trim(),ssl_keyfile:sf.ssl_keyfile.value.trim()},restream:{...(settings.restream||{}),enabled:sf.restream_enabled.checked,client_id:sf.restream_client_id.value.trim(),client_secret:sf.restream_client_secret.value},obs:{...(settings.obs||{}),enabled:sf.obs_enabled.checked,host:sf.obs_host.value.trim(),port:Number(sf.obs_port.value)||4455,password:sf.obs_password.value||settings.obs?.password||"",dropped_frames_threshold:Math.max(0,Number(sf.obs_dropped_frames_threshold.value)||0),preview_url:sf.obs_preview_url.value.trim()},ndi:{enabled:sf.ndi_enabled.checked,runtime_directory:sf.ndi_runtime_directory.value.trim()},intercom:{...(settings.intercom||{}),enabled:sf.intercom_enabled.checked,party_lines:sf.intercom_party_lines.value.split("\n").map(name=>name.trim()).filter(Boolean).map((name,index)=>({id:name.toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"")||`line-${index+1}`,name}))},
    shure:{...(settings.shure||{}),enabled:sf.shure_enabled.checked,receivers:[],mics:micRows.filter(mic=>["shure","shure-slxd"].includes(mic.manufacturer||"shure")).map(({manufacturer,...mic})=>({...mic,name:String(mic.name).trim(),host:String(mic.host).trim(),port:Number(mic.port)||2202,channel:Number(mic.channel)||1,model:manufacturer==="shure-slxd"?"slxd":"qlx-ulx"}))},sennheiser:{...(settings.sennheiser||{}),enabled:sf.sennheiser_enabled.checked,receivers:[],mics:micRows.filter(mic=>mic.manufacturer==="sennheiser").map(({manufacturer,...mic})=>({...mic,name:String(mic.name).trim(),host:String(mic.host).trim(),port:Number(mic.port)||45,channel:Number(mic.channel)||1}))},open_sound_meter:{...(settings.open_sound_meter||{}),enabled:sf.osm_enabled.checked,reports_enabled:sf.osm_reports_enabled.checked,report_weighting:sf.osm_report_weighting.value,report_response:sf.osm_report_response.value,source_id:sf.osm_source_id.value},position_mic_map:micMap};
}

async function saveSettings(showStatus=true){
  const status=document.querySelector("#settings-status");if(showStatus)status.textContent="Saving…";
  settings=await api("/api/settings",{method:"PUT",body:JSON.stringify(settingsPayload())});
  sf.pc_secret.value="";if(showStatus)status.textContent="Saved";return settings;
}

sf.addEventListener("submit",async event=>{event.preventDefault();try{await saveSettings()}catch(error){document.querySelector("#settings-status").textContent=error.message}});
document.querySelector("#pc-test").addEventListener("click",async()=>{
  const status=document.querySelector("#pc-status");status.textContent="Saving and connecting…";
  try{
    await saveSettings(false);
    const result=await api("/api/integrations/planning-center/test",{method:"POST"});
    serviceTypeRows=result.items||[];settings.planning_center.service_types=serviceTypeRows;renderServiceTypes();await saveSettings(false);
    status.textContent=`Connected · ${result.count} service type${result.count===1?"":"s"}`;
    await loadPositionCatalog();
  }catch(error){status.textContent=error.message}
});
document.querySelector("#restream-connect").addEventListener("click",async()=>{const status=document.querySelector("#restream-status");status.textContent="Saving…";try{await saveSettings(false);location.href="/api/integrations/restream/connect"}catch(error){status.textContent=error.message}});
document.querySelector("#restream-test").addEventListener("click",async()=>{const status=document.querySelector("#restream-status");status.textContent="Testing…";try{await saveSettings(false);const result=await api("/api/integrations/restream/test",{method:"POST"});status.textContent=`Connected · ${result.count} destination${result.count===1?"":"s"}`;sf.restream_client_secret.value=""}catch(error){status.textContent=error.message}});

document.querySelector("#add-mic").addEventListener("click",()=>{micRows.push({id:micId(),name:`Mic ${micRows.length+1}`,manufacturer:"shure",host:"",port:2202,channel:1,position_key:""});sf.shure_enabled.checked=true;renderMicManager();document.querySelector("#settings-status").textContent="Unsaved microphone changes"});
document.querySelector("#mic-manager").addEventListener("input",event=>{const field=event.target.dataset.micField,row=event.target.closest("[data-mic-id]");if(!field||!row)return;const mic=micRows.find(item=>item.id===row.dataset.micId);if(!mic)return;mic[field]=field==="channel"?Number(event.target.value)||1:event.target.value;if(field==="manufacturer")mic.port=mic[field]==="sennheiser"?45:2202;document.querySelector("#settings-status").textContent="Unsaved microphone changes"});
document.querySelector("#mic-manager").addEventListener("click",event=>{const button=event.target.closest("[data-delete-mic]");if(!button)return;const row=button.closest("[data-mic-id]");micRows=micRows.filter(mic=>mic.id!==row.dataset.micId);renderMicManager();document.querySelector("#settings-status").textContent="Microphone removed — save to apply"});

const dialog=document.querySelector("#new-dialog");
document.querySelector("#new-dashboard").onclick=()=>dialog.showModal();
document.querySelector("#cancel-dashboard").onclick=()=>{dialog.querySelector("form").reset();dialog.close("cancel")};
dialog.querySelector("[name=name]").addEventListener("input",e=>{dialog.querySelector("[name=slug]").value=e.target.value.toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"")});
document.querySelector("#create-dashboard").addEventListener("click",async event=>{event.preventDefault();const name=dialog.querySelector("[name=name]").value.trim(),slug=dialog.querySelector("[name=slug]").value.trim();if(!name||!slug)return;try{await api("/api/dashboards",{method:"POST",body:JSON.stringify({id:slug,name,slug,background_color:"#0a0d12",columns:12,row_height:72,widgets:[]})});dialog.close();location.href=`/editor/${encodeURIComponent(slug)}`}catch(error){alert(error.message)}});

document.querySelector("#osm-test").addEventListener("click",async()=>{const status=document.querySelector("#osm-status");status.textContent="Checking OSM multicast…";try{await saveSettings(false);const result=await api("/api/integrations/osm/test",{method:"POST"});status.textContent=result.message}catch(error){status.textContent=error.message}});
document.querySelector("#ndi-test").addEventListener("click",async()=>{const status=document.querySelector("#ndi-status");status.textContent="Saving and searching for the NDI runtime…";try{sf.ndi_enabled.checked=true;await saveSettings(false);const result=await api("/api/integrations/ndi/sources");if(result.available){const location=result.runtime_path?` · ${result.runtime_path}`:"";status.textContent=result.items?.length?`Runtime found${location} · ${result.items.length} source${result.items.length===1?"":"s"} found`:`Runtime found${location} · no sources advertised yet`;if(!sf.ndi_runtime_directory.value&&result.runtime_path)sf.ndi_runtime_directory.value=result.runtime_path}else status.textContent=result.error||"NDI runtime not found"}catch(error){status.textContent=error.message}});
loadDashboards();loadSettings();
