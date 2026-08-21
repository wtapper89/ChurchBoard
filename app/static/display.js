let dashboard,lastState={},serverInstance="",refreshInFlight=false,planOptionsKey="",serviceTimeOptionsKey="",planSelectionInFlight=false,lastFullRefresh=0,compactEtag="",ppKeyboardInFlight=false,prodmeshSocket=null,prodmeshReconnectTimer=0;
const mixerDragging=new Set(),mixerSendTimers=new Map();
const widgetRenderKeys=new Map();
const orderScrollPositions=new Map();
const playlistScrollPositions=new Map();
const playlistActiveKeys=new Map();
const objectIds=new WeakMap();let nextObjectId=1;
const slug=decodeURIComponent(location.pathname.split("/").pop());
document.querySelector("#edit-board-button").href=`/editor/${encodeURIComponent(slug)}`;
function inlineEditorFinish(savedDashboard){document.body.classList.add("inline-editor-closing");setTimeout(()=>{dashboard=savedDashboard||dashboard;const root=document.querySelector("#editor-grid");if(root){root.id="dashboard";root.classList.remove("editor-grid")}document.querySelectorAll(".inline-editor-chrome").forEach(element=>element.hidden=true);document.body.classList.remove("inline-editor-mode","inline-editor-closing","admin-shell");document.body.classList.add("display-page");if(location.search)history.replaceState({},"",location.pathname);widgetRenderKeys.clear();render()},260)}
async function openInlineEditor(){
  const existing=[...document.querySelectorAll(".inline-editor-chrome")];
  document.body.classList.add("inline-editor-mode","admin-shell");document.body.classList.remove("display-page");
  const root=document.querySelector("#dashboard");if(root){root.id="editor-grid";root.classList.add("editor-grid")}
  window.ChurchBoardInlineEditor={slug,getLiveState:()=>lastState,finish:inlineEditorFinish};
  if(existing.length){existing.forEach(element=>{element.hidden=!element.matches(".topbar,.palette,.editor-title")});window.ChurchBoardEditor?.reopen();return}
  const response=await fetch(`/editor/${encodeURIComponent(slug)}`);const html=await response.text(),page=new DOMParser().parseFromString(html,"text/html"),nodes=[page.querySelector(".topbar"),page.querySelector(".palette"),page.querySelector(".editor-title"),page.querySelector("#inspector-backdrop"),page.querySelector(".inspector"),page.querySelector("#widget-context")].filter(Boolean);
  if(nodes.length<6){location.href=`/editor/${encodeURIComponent(slug)}`;return}
  nodes.forEach(node=>{const imported=document.importNode(node,true);imported.classList.add("inline-editor-chrome");document.body.append(imported)});
  const script=document.createElement("script");script.src="/static/editor.js";document.body.append(script);
}
document.querySelector("#edit-board-button").addEventListener("click",event=>{event.preventDefault();openInlineEditor().catch(error=>{console.error(error);location.href=`/editor/${encodeURIComponent(slug)}`})});
document.addEventListener("click",event=>{if(document.body.classList.contains("inline-editor-mode")&&event.target.closest("#editor-grid [data-pp-trigger],#editor-grid [data-pp-playlist-trigger],#editor-grid [data-pp-nav],#editor-grid [data-pp-item-nav],#editor-grid [data-pp-macro],#editor-grid [data-board-destination],#editor-grid [data-service-action],#editor-grid [data-lighting-button],#editor-grid [data-mixer-mute]")){event.preventDefault();event.stopImmediatePropagation()}},true);
let dashboardFitFrame=0;
function fitDashboardToViewport(){
  const root=document.querySelector("#dashboard");if(!root)return;
  root.style.setProperty("--dashboard-scale","1");root.style.setProperty("--dashboard-fit-width","100%");root.style.setProperty("--dashboard-fit-height","100vh");
  void root.offsetWidth;
  const width=Math.max(root.scrollWidth,root.clientWidth),height=Math.max(root.scrollHeight,root.clientHeight),scale=Math.min(1,window.innerWidth/width,window.innerHeight/height);
  root.style.setProperty("--dashboard-scale",String(scale));root.style.setProperty("--dashboard-fit-width",`${100/scale}%`);root.style.setProperty("--dashboard-fit-height",`${100/scale}vh`);
}
function queueDashboardFit(){cancelAnimationFrame(dashboardFitFrame);dashboardFitFrame=requestAnimationFrame(fitDashboardToViewport)}
function updateNativeSpl(){const osm=lastState.osm||{};document.querySelectorAll("[data-spl-meter]").forEach(meter=>{const value=Number(osm[meter.dataset.osmKey||"a_fast"]),green=Number(meter.dataset.green),orange=Number(meter.dataset.orange),reading=meter.querySelector("[data-spl-value]"),status=meter.querySelector("[data-spl-status]");if(!osm.connected||!Number.isFinite(value)){if(reading)reading.textContent="--";if(status)status.textContent="Waiting for Open Sound Meter";meter.classList.remove("spl-green","spl-orange","spl-red");return}if(reading)reading.textContent=value.toFixed(1);meter.classList.toggle("spl-green",value<=green);meter.classList.toggle("spl-orange",value>green&&value<=orange);meter.classList.toggle("spl-red",value>orange);if(status)status.textContent=`${osm.source_name||"OSM source"} · ${meter.dataset.osmLabel||"level"}`})}
const triggerScope=element=>({dashboard_slug:slug,widget_id:element.closest(".widget")?.dataset.widget||null});
document.addEventListener("click",async event=>{const button=event.target.closest("[data-pp-trigger]");if(!button||button.disabled)return;const index=Number(button.dataset.ppTrigger),playlistIndex=Number(button.dataset.ppPlaylistIndex);if(!Number.isInteger(index)||index<0||!Number.isInteger(playlistIndex)||playlistIndex<0)return;button.disabled=true;try{await api("/api/integrations/propresenter/active-slide",{method:"POST",body:JSON.stringify({index,playlist_index:playlistIndex,presentation_uuid:button.dataset.ppPresentationUuid||null,is_pco:button.dataset.ppIsPco==="true",...triggerScope(button)})});await refresh(true)}catch(error){alert(error.message)}finally{button.disabled=false}});
document.addEventListener("click",async event=>{const button=event.target.closest("[data-pp-playlist-trigger]");if(!button||button.disabled)return;const index=Number(button.dataset.ppPlaylistTrigger);if(!Number.isInteger(index)||index<0)return;button.disabled=true;try{await api("/api/integrations/propresenter/active-playlist-item",{method:"POST",body:JSON.stringify({index,presentation_uuid:button.dataset.ppPresentationUuid||null,is_pco:button.dataset.ppIsPco==="true",...triggerScope(button)})})}catch(error){alert(error.message)}finally{button.disabled=false}});
document.addEventListener("click",async event=>{const button=event.target.closest("[data-pp-nav],[data-pp-item-nav]");if(!button||button.disabled)return;const direction=button.dataset.ppNav||button.dataset.ppItemNav,endpoint=button.dataset.ppItemNav?"navigate-item":"navigate",status=button.closest(".pp-control-pad")?.querySelector("[data-pp-control-status]");button.disabled=true;if(status)status.textContent=direction==="next"?"Advancing ProPresenter…":"Going back in ProPresenter…";try{await api(`/api/integrations/propresenter/${endpoint}/${direction}`,{method:"POST",body:JSON.stringify(triggerScope(button))});await refresh(true)}catch(error){if(status)status.textContent=error.message}finally{button.disabled=false}});
document.addEventListener("click",async event=>{const button=event.target.closest("[data-pp-macro]");if(!button||button.disabled)return;button.disabled=true;button.classList.add("triggering");try{await api("/api/integrations/propresenter/macro",{method:"POST",body:JSON.stringify({macro_id:button.dataset.ppMacro,...triggerScope(button)})});button.classList.add("triggered");setTimeout(()=>button.classList.remove("triggered"),550)}catch(error){alert(error.message)}finally{button.disabled=false;button.classList.remove("triggering")}});
document.addEventListener("click",event=>{const link=event.target.closest("[data-board-destination]");if(!link)return;event.preventDefault();location.assign(`/display/${encodeURIComponent(link.dataset.boardDestination)}`)});
document.addEventListener("click",async event=>{const button=event.target.closest("[data-lighting-button]");if(!button||button.disabled)return;button.disabled=true;try{await api("/api/integrations/lighting/button",{method:"POST",body:JSON.stringify({name:button.dataset.lightingButton,mode:"toggle",...triggerScope(button)})});await loadLightingButtons(button.closest(".widget"),true)}catch(error){alert(error.message)}finally{button.disabled=false}});
async function sendMixerControl(element,values){if(document.body.classList.contains("inline-editor-mode"))return;const widget=element.closest(".widget"),strip=element.closest("[data-mixer-strip]");if(!widget||!strip)return;try{await api("/api/integrations/behringer/control",{method:"POST",body:JSON.stringify({...triggerScope(element),strip_id:strip.dataset.mixerStrip,...values})})}catch(error){alert(error.message)}}
document.addEventListener("pointerdown",event=>{const fader=event.target.closest("[data-mixer-fader]");if(fader)mixerDragging.add(String(fader.closest(".widget")?.dataset.widget||""))});
document.addEventListener("pointerup",event=>{const fader=event.target.closest("[data-mixer-fader]");if(!fader)return;const widgetId=String(fader.closest(".widget")?.dataset.widget||"");mixerDragging.delete(widgetId);widgetRenderKeys.delete(widgetId)});
document.addEventListener("input",event=>{const fader=event.target.closest("[data-mixer-fader]");if(!fader)return;const db=x32FaderToDb(fader.value),output=fader.closest("[data-mixer-strip]")?.querySelector("[data-mixer-db]");if(output)output.textContent=`${mixerDbLabel(db)} dB`;const key=`${fader.closest(".widget")?.dataset.widget}:${fader.dataset.mixerFader}`;clearTimeout(mixerSendTimers.get(key));mixerSendTimers.set(key,setTimeout(()=>sendMixerControl(fader,{level_db:Number.isFinite(db)?db:-100}),65))});
document.addEventListener("change",event=>{const fader=event.target.closest("[data-mixer-fader]");if(!fader)return;const bottom=Number(fader.value)<=.035;if(bottom)fader.value=0;const db=bottom?-Infinity:x32FaderToDb(fader.value),output=fader.closest("[data-mixer-strip]")?.querySelector("[data-mixer-db]");if(output)output.textContent=`${mixerDbLabel(db)} dB`;sendMixerControl(fader,{level_db:Number.isFinite(db)?db:-100})});
document.addEventListener("click",event=>{const button=event.target.closest("[data-mixer-mute]");if(!button)return;const muted=!button.classList.contains("active");button.classList.toggle("active",muted);button.setAttribute("aria-pressed",String(muted));button.closest("[data-mixer-strip]")?.classList.toggle("muted",muted);sendMixerControl(button,{muted})});
async function loadLightingButtons(widget,force=false){const root=widget?.querySelector("[data-lighting-buttons]");if(!root||(!force&&root.dataset.loaded==="true"))return;try{const result=await api("/api/integrations/lighting/buttons");root.dataset.loaded="true";root.innerHTML=(result.items||[]).map(item=>`<button type="button" data-lighting-button="${escapeHtml(item.name)}" class="${item.pressed?"active":""}" style="--cue-color:${safeCssColor(item.color)}"><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.page)}</span></button>`).join("")||'<div class="empty">No lighting buttons are exposed</div>'}catch(error){root.innerHTML=`<div class="empty">${escapeHtml(error.message)}</div>`}}
const keyboardStorageKey=widgetId=>`churchboard:${slug}:propresenter-keyboard:${widgetId}`;
function syncPlaylistOperatorToggles(root=document){root.querySelectorAll('[data-widget-type="playlist"]').forEach(element=>{const widgetId=element.dataset.widget,controls=element.querySelector("[data-pp-controls-toggle]"),keyboard=element.querySelector("[data-pp-keyboard-toggle]");if(!keyboard)return;const controlsEnabled=!!controls?.checked,stored=localStorage.getItem(keyboardStorageKey(widgetId)),enabled=stored===null?keyboard.dataset.defaultChecked==="true":stored==="true";keyboard.disabled=!controlsEnabled;keyboard.checked=controlsEnabled&&enabled})}
function keyboardPlaylistWidget(){const toggle=document.querySelector('[data-widget-type="playlist"] [data-pp-keyboard-toggle]:checked:not(:disabled)'),widgetId=toggle?.closest(".widget")?.dataset.widget;return(dashboard?.widgets||[]).find(widget=>String(widget.id)===String(widgetId))}
function setPlaylistKeyboardStatus(message,isError=false){document.querySelectorAll("[data-pp-keyboard-status]").forEach(element=>{element.textContent=message;element.classList.toggle("error",isError)})}
document.addEventListener("change",async event=>{
  const keyboard=event.target.closest("[data-pp-keyboard-toggle]");if(keyboard){const widgetId=keyboard.closest(".widget")?.dataset.widget;if(widgetId)localStorage.setItem(keyboardStorageKey(widgetId),String(keyboard.checked));setPlaylistKeyboardStatus(keyboard.checked?"←/↑ back · →/↓/Space next":"");return}
  const controls=event.target.closest("[data-pp-controls-toggle]");if(!controls)return;const widgetId=controls.closest(".widget")?.dataset.widget,widget=(dashboard?.widgets||[]).find(item=>String(item.id)===String(widgetId));if(!widget)return;controls.disabled=true;widget.settings={...(widget.settings||{}),allow_remote_trigger:controls.checked};if(!controls.checked)localStorage.setItem(keyboardStorageKey(widgetId),"false");try{dashboard=await api(`/api/dashboards/${encodeURIComponent(dashboard.id)}`,{method:"PUT",body:JSON.stringify(dashboard)});widgetRenderKeys.delete(String(widgetId));render()}catch(error){widget.settings.allow_remote_trigger=!controls.checked;controls.checked=!controls.checked;controls.disabled=false;alert(error.message)}
});
document.addEventListener("keydown",async event=>{
  const playlistWidget=keyboardPlaylistWidget();if(!playlistWidget||ppKeyboardInFlight||event.defaultPrevented||event.repeat||event.metaKey||event.ctrlKey||event.altKey)return;
  const target=event.target;if(target instanceof Element&&(target.closest("input,textarea,select,button,a,[contenteditable=true]")||target.closest(".display-menu.open")))return;
  const direction=["ArrowLeft","ArrowUp"].includes(event.key)?"previous":["ArrowRight","ArrowDown"," "].includes(event.key)?"next":"";if(!direction)return;
  event.preventDefault();ppKeyboardInFlight=true;setPlaylistKeyboardStatus(direction==="next"?"Advancing ProPresenter…":"Going back in ProPresenter…");
  try{await api(`/api/integrations/propresenter/navigate/${direction}`,{method:"POST",body:JSON.stringify({dashboard_slug:slug,widget_id:playlistWidget.id})});await refresh(true);setPlaylistKeyboardStatus("Keyboard: ←/↑ back · →/↓/Space next")}
  catch(error){setPlaylistKeyboardStatus(error.message,true)}finally{ppKeyboardInFlight=false}
});
async function loadBoard(){
  await loadChurchBoardModules();
  dashboard=await api(`/api/dashboards/${encodeURIComponent(slug)}`);
  document.title=`${dashboard.name} · ChurchBoard`;
  dashboard.background_color=applyDashboardAppearance(document.body,dashboard.background_color);
  const root=document.querySelector("#dashboard");
  root.style.setProperty("--columns",dashboard.columns); root.style.setProperty("--row-height",`${dashboard.row_height}px`);
  root.innerHTML="";widgetRenderKeys.clear();
  await refresh(true);
}
const sameJson=(left,right)=>JSON.stringify(left)===JSON.stringify(right);
const retainCachedValue=(previous,next)=>previous!==undefined&&sameJson(previous,next)?previous:next;
function mergeFullState(fresh){
  if(!Object.keys(lastState).length)return fresh;
  for(const key of ["service","people","plans","planning_center_media"]){
    if(key in fresh)fresh[key]=retainCachedValue(lastState[key],fresh[key]);
  }
  if(fresh.timing&&lastState.timing&&fresh.timing.service_items){
    fresh.timing.service_items=retainCachedValue(lastState.timing.service_items,fresh.timing.service_items);
  }
  if(lastState.prodmesh_rta?.transport==="websocket"&&Number(lastState.prodmesh_rta.time_ms)>Number(fresh.prodmesh_rta?.time_ms||0))fresh.prodmesh_rta=lastState.prodmesh_rta;
  return fresh;
}
function mergeCompactState(fresh){
  const previousTiming=lastState.timing||{},incomingTiming=fresh.timing||{};
  const previousProPresenter=lastState.propresenter||{},incomingProPresenter=fresh.propresenter||{};
  const activeUuid=String(incomingProPresenter.presentation_uuid||previousProPresenter.presentation_uuid||""),playlistPresentations=(previousProPresenter.playlist_presentations||[]).map(item=>({...item,active:!!activeUuid&&String(item.presentation_uuid||"")===activeUuid}));
  return {...lastState,...fresh,timing:{...previousTiming,...incomingTiming,service_items:previousTiming.service_items},propresenter:{...previousProPresenter,...incomingProPresenter,playlist_presentations:playlistPresentations,slides:previousProPresenter.slides}};
}
async function compactRuntime(){
  const response=await fetch("/api/runtime?compact=true",{headers:compactEtag?{"If-None-Match":compactEtag}:{}});
  if(response.status===304)return null;
  if(!response.ok)throw new Error((await response.json().catch(()=>({}))).detail||`Request failed (${response.status})`);
  compactEtag=response.headers.get("ETag")||"";return response.json();
}
async function refresh(forceFull=false){
  if(refreshInFlight)return;
  refreshInFlight=true;
  try{
    const now=Date.now(),full=forceFull||!lastFullRefresh||now-lastFullRefresh>=5000,fresh=full?await api("/api/runtime"):await compactRuntime();
    if(!fresh)return;
    lastState=full?mergeFullState(fresh):mergeCompactState(fresh);if(full)lastFullRefresh=now;
    render();updatePlans();
  }catch(error){console.error(error)}finally{refreshInFlight=false}
}
async function checkServerInstance(){try{const info=await api("/api/app-info");if(serverInstance&&serverInstance!==info.instance_id){location.reload();return}serverInstance=info.instance_id}catch(error){}}
function connectProdMeshStream(){clearTimeout(prodmeshReconnectTimer);if(prodmeshSocket&&[WebSocket.CONNECTING,WebSocket.OPEN].includes(prodmeshSocket.readyState))return;const scheme=location.protocol==="https:"?"wss":"ws";prodmeshSocket=new WebSocket(`${scheme}://${location.host}/api/integrations/prodmesh-rta/stream`);prodmeshSocket.onmessage=event=>{try{const frame=JSON.parse(event.data),currentTime=Number(lastState.prodmesh_rta?.time_ms||0),frameTime=Number(frame.time_ms||0);if(frameTime&&frameTime<currentTime)return;lastState={...lastState,prodmesh_rta:frame};render()}catch(error){console.warn("Invalid ProdMesh stream frame",error)}};prodmeshSocket.onclose=()=>{prodmeshSocket=null;prodmeshReconnectTimer=setTimeout(connectProdMeshStream,1000)};prodmeshSocket.onerror=()=>prodmeshSocket?.close()}
function render(){
  const root=document.querySelector("#dashboard");if(!root){window.ChurchBoardEditor?.setRuntime(lastState);return}const widgets=dashboard.widgets||[],existing=new Map([...root.querySelectorAll(":scope > .widget")].map(element=>[String(element.dataset.widget),element])),activeIds=new Set(),timing=lastState.timing||{};
  let changed=false;
  for(const widget of widgets){
    const id=String(widget.id),renderKey=widgetStateKey(widget,lastState);
    activeIds.add(id);
    if(widget.type==="behringer_faders"&&mixerDragging.has(id))continue;
    if(widgetRenderKeys.get(id)===renderKey&&existing.has(id))continue;
    const current=existing.get(id),previousList=current?.querySelector(".full-service-order-list"),previousPlaylist=current?.querySelector(".pp-browser-scroll");if(previousList)orderScrollPositions.set(id,previousList.scrollTop);if(previousPlaylist)playlistScrollPositions.set(id,previousPlaylist.scrollTop);
    const markup=widgetMarkup(widget,lastState);
    const template=document.createElement("template");template.innerHTML=markup.trim();const replacement=template.content.firstElementChild;
    if(current)current.replaceWith(replacement);else root.append(replacement);
    const replacementList=replacement.querySelector(".full-service-order-list"),savedScroll=orderScrollPositions.get(id);if(replacementList){if(savedScroll!==undefined)replacementList.scrollTop=savedScroll;replacementList.addEventListener("scroll",()=>orderScrollPositions.set(id,replacementList.scrollTop),{passive:true})}
    const replacementPlaylist=replacement.querySelector(".pp-browser-scroll"),savedPlaylistScroll=playlistScrollPositions.get(id);if(replacementPlaylist){if(savedPlaylistScroll!==undefined)replacementPlaylist.scrollTop=savedPlaylistScroll;replacementPlaylist.addEventListener("scroll",()=>playlistScrollPositions.set(id,replacementPlaylist.scrollTop),{passive:true})}
    widgetRenderKeys.set(id,renderKey);changed=true;
  }
  for(const [id,element] of existing){if(!activeIds.has(id)){element.remove();widgetRenderKeys.delete(id);orderScrollPositions.delete(id);playlistScrollPositions.delete(id);changed=true}}
  if(!widgets.length&&root.innerHTML!==`<div class="empty">This dashboard has no widgets.</div>`){root.innerHTML=`<div class="empty">This dashboard has no widgets.</div>`;changed=true}
  updateTimingWidgets();updateOrderTimingWidgets();
  if(changed){tickClocks();enhanceDynamicContent(root);syncPlaylistOperatorToggles(root);root.querySelectorAll('[data-widget-type="lighting"]').forEach(widget=>loadLightingButtons(widget))}
  updatePlaylistLiveState(root);
  queueDashboardFit();
  updateNativeSpl();
}
function objectId(value){if(!value||typeof value!=="object")return String(value);if(!objectIds.has(value))objectIds.set(value,nextObjectId++);return objectIds.get(value)}
function leaderMicKey(mics){return(mics||[]).map(mic=>[mic.id,mic.name,mic.receiver,mic.assignment?.person_id,mic.assignment?.id,mic.assignment?.name,mic.assignment?.position_key])}
function widgetStateKey(widget,state){
  const timing=state.timing||{},service=state.service||{},pp=state.propresenter||{},settings=widget.settings||{};
  if(widget.type==="clock"||widget.type==="spl"||widget.type==="text")return`${widget.type}:static`;
  if(widget.type==="board_navigation")return`board-navigation:${JSON.stringify(settings.links||[])}`;
  if(widget.type==="service")return`service:${objectId(service)}:${timing.source||""}:${timing.state||""}`;
  if(widget.type==="timing")return`timing:${String(timing.current_item?.id||"")}:${timing.rehearsal===true}`;
  if(["assignments","mics"].includes(widget.type))return`${widget.type}:${JSON.stringify([state.people||[],state.mics||[],state.planning_center_media||{}])}`;
  if(widget.type==="slides"||widget.type==="producer")return`${widget.type}:${JSON.stringify([pp,service,timing])}`;
  if(widget.type==="playlist"){const rows=(pp.playlist_presentations||[]).map(item=>({index:item.index,title:item.title,presentation_uuid:item.presentation_uuid,is_pco:item.is_pco,triggerable:item.triggerable,type:item.type,slides:(item.slides||[]).map(slide=>({index:slide.index,part:slide.part,color:slide.color,image_url:slide.image_url}))}));return`playlist:${JSON.stringify([pp.playlist_name,pp.title,pp.planning_center_item_title,rows,settings])}`}
  if(widget.type==="pp_controls")return`pp-controls:${String(pp.presentation_uuid||"")}:${String(pp.title||"")}`;
  if(widget.type==="pp_macros")return`pp-macros:${JSON.stringify([pp.macros||[],settings])}`;
  if(widget.type==="notes")return`notes:${String(pp.current?.notes||"")}`;
  if(widget.type==="sermon_notes")return`sermon-notes:${objectId(timing.service_items||service.items)}:${JSON.stringify(settings)}`;
  if(widget.type==="order")return`order:${objectId(timing.service_items||service.items)}:${objectId(state.people)}:${JSON.stringify(leaderMicKey(state.mics))}:${String(timing.current_item?.id||"")}:${timing.service_time_id||""}:${settings.show_leader!==false}:${settings.show_mic!==false}:${!!settings.show_production_note}:${JSON.stringify(settings.production_note_fields||[settings.production_note_field||""])}:${JSON.stringify(settings.production_note_colors||{})}`;
  if(widget.type==="people"||widget.type==="person")return`${widget.type}:${objectId(state.people)}`;
  if(widget.type==="controls")return`controls:${JSON.stringify([state.planning_center_live||{},state.service_control||{},timing.current_item?.id,timing.current_item?.title])}`;
  if(widget.type==="restream")return`restream:${JSON.stringify(state.restream||{})}`;
  if(widget.type==="livestreams")return`livestreams:${JSON.stringify([state.livestreams||[],settings.sources||[]])}`;
  if(widget.type==="propresenter_timers")return`propresenter-timers:${JSON.stringify(pp.timers||[])}`;
  if(widget.type==="ndi")return`ndi:${settings.source_name||""}`;
  if(widget.type==="webcam")return`webcam:${JSON.stringify(settings)}`;
  if(widget.type==="prodmesh_rta")return`prodmesh-rta:${JSON.stringify(state.prodmesh_rta||{})}:${JSON.stringify(settings)}`;
  if(widget.type==="behringer_faders")return`behringer:${JSON.stringify(state.behringer||{})}:${JSON.stringify(settings)}`;
  if(widget.type==="lighting")return`lighting:${JSON.stringify(settings)}`;
  return`${widget.type}:${JSON.stringify(state)}`;
}
function updatePlaylistLiveState(root=document){const pp=lastState.propresenter||{},uuid=String(pp.presentation_uuid||""),slide=Number(pp.current?.index)||0;root.querySelectorAll('[data-widget-type="playlist"]').forEach(widget=>{const widgetId=String(widget.dataset.widget||""),key=`${uuid}:${slide}`;widget.querySelectorAll("[data-pp-item-uuid]").forEach(item=>{const active=String(item.dataset.ppItemUuid||"")===uuid;item.classList.toggle("active",active);const status=item.querySelector("[data-pp-item-status]");if(status)status.textContent=active?"On air":status.dataset.idleLabel||""});widget.querySelectorAll("[data-pp-slide-uuid]").forEach(item=>item.classList.toggle("active",String(item.dataset.ppSlideUuid||"")===uuid&&Number(item.dataset.ppSlideNumber)===slide));if(playlistActiveKeys.get(widgetId)===key)return;playlistActiveKeys.set(widgetId,key);const configured=(dashboard?.widgets||[]).find(item=>String(item.id)===widgetId);if(configured?.settings?.auto_scroll===false)return;const target=widget.querySelector(".pp-list-slide.active")||widget.querySelector(".pp-list-presentation.active");target?.scrollIntoView({block:"nearest",inline:"nearest",behavior:"smooth"})})}
function fitOrderService(root=document){
  root.querySelectorAll(".order-list").forEach(list=>{
    if(list.classList.contains("full-service-order-list"))return;
    const rows=[...list.querySelectorAll("li")];if(!rows.length)return;
    rows.forEach(row=>row.classList.remove("order-hidden"));list.classList.remove("priority-window");
    if(list.classList.contains("full-service-order-fit-list")||list.classList.contains("current-service-order-list")){
      const minimum=list.classList.contains("full-service-order-fit-list")?1:.72;list.style.setProperty("--order-fit-scale",minimum);
      if(list.scrollHeight<=list.clientHeight+1&&list.scrollWidth<=list.clientWidth+1){let low=minimum,high=1.35,best=minimum;for(let pass=0;pass<9;pass++){const scale=(low+high)/2;list.style.setProperty("--order-fit-scale",scale);if(list.scrollHeight<=list.clientHeight+1&&list.scrollWidth<=list.clientWidth+1){best=scale;low=scale}else high=scale}list.style.setProperty("--order-fit-scale",best);return}
      list.classList.add("priority-window");
    }
    const foundActive=rows.findIndex(row=>row.classList.contains("active")),activeIndex=foundActive>=0?foundActive:0,heights=rows.map(row=>Math.ceil(row.getBoundingClientRect().height)),available=Math.max(0,list.clientHeight-2),priority=[];
    priority.push(activeIndex);
    let upcomingItems=0;
    for(let index=activeIndex+1;index<rows.length&&upcomingItems<3;index++)if(!rows[index].classList.contains("order-header")){priority.push(index);upcomingItems++}
    for(let index=activeIndex+1;index<rows.length;index++)if(rows[index].classList.contains("order-header"))priority.push(index);
    for(let offset=1;offset<=2;offset++)if(activeIndex-offset>=0)priority.push(activeIndex-offset);
    for(let offset=1;activeIndex+offset<rows.length;offset++)priority.push(activeIndex+offset);
    for(let offset=3;activeIndex-offset>=0;offset++)priority.push(activeIndex-offset);
    const visible=new Set();let used=0;
    for(const index of priority){if(visible.has(index))continue;const height=heights[index];if(!visible.size||used+height<=available){visible.add(index);used+=height}}
    rows.forEach((row,index)=>row.classList.toggle("order-hidden",!visible.has(index)));list.scrollTop=0;
  });
}
function updateTimingWidgets(){
  const timing=lastState.timing||{},item=timing.current_item,cells=document.querySelectorAll('[data-widget-type="timing"] .timing-cell');let changed=false;
  if(cells[0]){const label=cells[0].querySelector(".timing-label"),value=cells[0].querySelector(".timing-value"),labelText=item?.title||"Current item",valueText=formatDuration(timing.item_delta||0);if(label&&label.textContent!==labelText){label.textContent=labelText;changed=true}if(value){if(value.textContent!==valueText){value.textContent=valueText;changed=true}value.classList.toggle("over",(timing.item_delta||0)>0);value.classList.toggle("ahead",(timing.item_delta||0)<=0)}}
  if(cells[1]){const value=cells[1].querySelector(".timing-value"),valueText=formatDuration(timing.overall_delta||0);if(value){if(value.textContent!==valueText){value.textContent=valueText;changed=true}value.classList.toggle("over",(timing.overall_delta||0)>0);value.classList.toggle("ahead",(timing.overall_delta||0)<=0)}}
  if(changed)requestAnimationFrame(()=>resizeDashboardContent(document.querySelector("#dashboard")));
}
function updateOrderTimingWidgets(){
  const timing=lastState.timing||{},service=lastState.service||{},adjusting=["running","live","controlled"].includes(timing.state),drift=Number(timing.overall_delta||0),driftLabel=adjusting&&Math.abs(drift)>=30?`${formatDuration(drift)} ${drift>0?"late":"early"}`:"On time",start=Date.parse(timing.service_start_at||service.starts_at||"");
  document.querySelectorAll("[data-order-drift]").forEach(element=>{if(element.textContent!==driftLabel)element.textContent=driftLabel});
  document.querySelectorAll("[data-order-eta]").forEach(element=>{const value=Number.isFinite(start)?formatClockTime(new Date(start+Number(element.dataset.startsAfter||0)*1000+(adjusting?drift:0)*1000),lastState.timezone):"—";if(element.textContent!==value)element.textContent=value});
}
document.addEventListener("click",async event=>{
  const orderJump=event.target.closest("[data-order-jump]");if(orderJump){const list=orderJump.closest(".order-layout")?.querySelector(".full-service-order-list");if(!list)return;const target=orderJump.dataset.orderJump;if(target==="start")list.scrollTo({top:0,behavior:"smooth"});else if(target==="end")list.scrollTo({top:list.scrollHeight,behavior:"smooth"});else list.querySelector("li.active")?.scrollIntoView({block:"center",behavior:"smooth"});return}
  const button=event.target.closest("[data-service-action]");if(!button)return;button.disabled=true;const status=button.closest(".service-controls")?.querySelector("[data-control-status]");if(status)status.textContent="Updating…";
  try{lastState=await api(`/api/service-control/${button.dataset.serviceAction}`,{method:"POST"});render();updatePlans()}catch(error){button.disabled=false;if(status)status.textContent=error.message}
});
const displayMenu=document.querySelector(".display-menu"),menuButton=document.querySelector(".hamburger");
function setMenuOpen(open){displayMenu.classList.toggle("open",open);document.body.classList.toggle("display-menu-open",open);displayMenu.setAttribute("aria-hidden",String(!open));menuButton.setAttribute("aria-expanded",String(open));menuButton.setAttribute("aria-label",open?"Close menu":"Open menu")}
menuButton.addEventListener("click",event=>{event.stopPropagation();setMenuOpen(!displayMenu.classList.contains("open"))});
document.addEventListener("click",event=>{if(displayMenu.classList.contains("open")&&!displayMenu.contains(event.target)&&!menuButton.contains(event.target))setMenuOpen(false)});
document.addEventListener("keydown",event=>{if(event.key==="Escape"&&displayMenu.classList.contains("open")){setMenuOpen(false);menuButton.focus()}});
const fullscreenButton=document.querySelector(".fullscreen-toggle");
const fullscreenElement=()=>document.fullscreenElement||document.webkitFullscreenElement;
function updateFullscreenButton(){const active=!!fullscreenElement();fullscreenButton.classList.toggle("is-fullscreen",active);fullscreenButton.textContent=active?"↙":"⛶";fullscreenButton.setAttribute("aria-label",active?"Exit fullscreen":"Enter fullscreen");fullscreenButton.title=active?"Exit fullscreen":"Enter fullscreen"}
fullscreenButton.addEventListener("click",async()=>{try{if(fullscreenElement()){const exit=document.exitFullscreen||document.webkitExitFullscreen;if(exit)await exit.call(document)}else{const enter=document.documentElement.requestFullscreen||document.documentElement.webkitRequestFullscreen;if(enter)await enter.call(document.documentElement)}}catch(error){console.error(error)}updateFullscreenButton()});
document.addEventListener("fullscreenchange",()=>{updateFullscreenButton();queueDashboardFit()});document.addEventListener("webkitfullscreenchange",()=>{updateFullscreenButton();queueDashboardFit()});window.addEventListener("resize",queueDashboardFit,{passive:true});updateFullscreenButton();
function updatePlans(){
  const select=document.querySelector("#active-plan"),plans=lastState.plans||[],optionsKey=JSON.stringify(plans.map(plan=>[plan.service_type_id,plan.id,plan.title||plan.service_type_name,plan.dates||""]));
  if(optionsKey!==planOptionsKey){select.innerHTML='<option value="">Automatic</option>'+plans.map(plan=>`<option value="${escapeHtml(plan.service_type_id)}:${escapeHtml(plan.id)}">${escapeHtml(plan.title||plan.service_type_name)} · ${escapeHtml(plan.dates||"")}</option>`).join("");planOptionsKey=optionsKey}
  if(planSelectionInFlight)return;
  const manual=lastState.manual_plan,desired=manual?`${manual.service_type_id}:${manual.id}`:"";
  if(select.value!==desired)select.value=desired;
  updateServiceTimes();
}
function updateServiceTimes(){const select=document.querySelector("#active-service-time"),service=lastState.service||{},times=service.times||[],key=JSON.stringify(times.map(row=>[row.id,row.name,row.starts_at]));if(key!==serviceTimeOptionsKey){select.innerHTML='<option value="">Automatic for current time</option>'+times.map(row=>`<option value="${escapeHtml(String(row.id||""))}">${escapeHtml(row.name||new Date(row.starts_at).toLocaleTimeString([],{hour:"numeric",minute:"2-digit"}))}</option>`).join("");serviceTimeOptionsKey=key}const manual=lastState.manual_service_time||{};select.value=String(manual.plan_id||"")===String(service.id||"")?String(manual.id||""):"";select.disabled=!times.length}
document.querySelector("#active-plan").addEventListener("change",async event=>{
  const select=event.currentTarget,status=document.querySelector("#active-plan-status"),[service_type_id,id]=select.value.split(":");
  planSelectionInFlight=true;select.disabled=true;status.textContent="Selecting service…";
  try{lastState=await api("/api/active-plan",{method:"PUT",body:JSON.stringify(id?{id,service_type_id}:{})});render();status.textContent="";setMenuOpen(false)}
  catch(error){status.textContent=error.message}
  finally{planSelectionInFlight=false;select.disabled=false;updatePlans()}
});
document.querySelector("#active-service-time").addEventListener("change",async event=>{const select=event.currentTarget,status=document.querySelector("#active-service-time-status");select.disabled=true;status.textContent="Selecting service time…";try{lastState=await api("/api/active-service-time",{method:"PUT",body:JSON.stringify({id:select.value||null,plan_id:lastState.service?.id||null})});render();status.textContent="";setMenuOpen(false)}catch(error){status.textContent=error.message}finally{select.disabled=false;updateServiceTimes()}});
document.addEventListener("click",event=>{const link=event.target.closest("[data-board-menu-edit]");if(!link||link.dataset.boardMenuEdit!==slug)return;event.preventDefault();setMenuOpen(false);openInlineEditor()});
api("/api/dashboards").then(data=>document.querySelector("#board-links").innerHTML=data.items.map(item=>`<div class="board-menu-row"><a class="board-menu-open" href="/display/${encodeURIComponent(item.slug)}">${escapeHtml(item.name)}</a><a class="board-menu-edit" data-board-menu-edit="${escapeHtml(item.slug)}" href="/display/${encodeURIComponent(item.slug)}?edit=1" aria-label="Edit ${escapeHtml(item.name)}">Edit</a></div>`).join(""));
checkServerInstance();connectProdMeshStream();loadBoard().then(()=>{if(new URLSearchParams(location.search).get("edit")==="1")openInlineEditor()}); setInterval(refresh,150); setInterval(tickClocks,250);setInterval(checkServerInstance,5000);
