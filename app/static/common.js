const api = async (url, options={}) => {
  const response = await fetch(url, {headers:{"Content-Type":"application/json", ...(options.headers||{})}, ...options});
  if (!response.ok) throw new Error((await response.json().catch(()=>({}))).detail || `Request failed (${response.status})`);
  return response.status === 204 ? null : response.json();
};
const escapeHtml = value => String(value ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
const formatDuration = seconds => {
  const value = Math.round(Number(seconds)||0), sign=value>0?"+":value<0?"−":"", abs=Math.abs(value);
  return `${sign}${Math.floor(abs/60)}:${String(abs%60).padStart(2,"0")}`;
};
const initials = name => String(name||"?").split(/\s+/).slice(0,2).map(part=>part[0]).join("").toUpperCase();
const safeCssColor = value => {
  const color=String(value||"").trim();
  return /^(#[0-9a-f]{6}(?:[0-9a-f]{2})?|rgba?\([\d.,\s]+\))$/i.test(color)?color:"#65a9ff";
};
const dashboardColor = value => /^#[0-9a-f]{6}$/i.test(String(value||""))?String(value).toLowerCase():"#0a0d12";
const applyDashboardAppearance = (target,value) => {
  const color=dashboardColor(value);
  target.style.setProperty("--board-color",color);
  target.style.setProperty("--board-effect",`color-mix(in srgb,${color} 48%,white)`);
  return color;
};
const contrastText = value => {
  const color=safeCssColor(value);let channels,alpha=1;
  if(color.startsWith("#")){channels=[parseInt(color.slice(1,3),16),parseInt(color.slice(3,5),16),parseInt(color.slice(5,7),16)];if(color.length===9)alpha=parseInt(color.slice(7,9),16)/255}
  else{const values=(color.match(/[\d.]+/g)||[]).map(Number);channels=values.slice(0,3);alpha=values[3]??1}
  const base=[9,13,19];channels=channels.map((channel,index)=>channel*alpha+base[index]*(1-alpha));
  return channels[0]*.299+channels[1]*.587+channels[2]*.114>150?"#080b10":"#fff";
};
const partBug = (slide,label) => { const color=safeCssColor(slide.color),kind=label.toLocaleLowerCase(); return `<div class="part-chip part-${kind}" style="--part-color:${color};--part-text:${contrastText(color)}"><span>${label}</span><strong>${escapeHtml(slide.part||"Unlabeled")}</strong></div>`; };
const slidePreview = (slide,label,{notes=false,mode="image",showLabel=true}={}) => {
  const image=mode==="image"&&slide.image_url?`<img class="slide-image" src="${escapeHtml(slide.image_url)}" alt="${label} slide preview">`:"";
  const timer=mode==="image"&&slide.timer_text?`<div class="slide-live-timer" data-fit-widget-text>${escapeHtml(slide.timer_text)}</div>`:"";
  const media=slide.media||{},video=mode==="image"&&media.is_playing&&!media.audio_only,position=Math.max(0,Number(media.position)||0),duration=Math.max(0,Number(media.duration)||0),progress=duration?Math.min(100,position/duration*100):0;
  const videoStatus=video?`<div class="slide-video-status"><div><strong>VIDEO · PLAYING</strong><span>${duration?`${formatMediaTime(position)} / ${formatMediaTime(duration)}`:"Live playback"}</span></div>${duration?`<div class="slide-video-track"><i style="width:${progress}%"></i></div>`:""}</div>`:"";
  const displayText=mode==="text"&&slide.timer_text?replaceSlideTimer(slide.text,slide.timer_text):(slide.text||"No active slide");
  return `<div class="slide ${label==="Now"?"current":""} mode-${mode}">${showLabel?`<div class="slide-label">${label}</div>`:""}<div class="slide-canvas ${video?"has-video":""}"><div class="slide-text" data-fit-slide>${escapeHtml(displayText)}</div>${image}${timer}${videoStatus}</div>${notes&&slide.notes?`<div class="slide-notes">${escapeHtml(slide.notes)}</div>`:""}</div>`;
};
const replaceSlideTimer = (text,timer) => String(text||"").split(/\r?\n/).map(line=>/^\s*-?\d{1,3}:\d{2}(?::\d{2})?(?:\.\d{1,2})?\s*$/.test(line)?timer:line).join("\n")||timer;
const formatMediaTime = seconds => {const value=Math.max(0,Math.round(Number(seconds)||0));return`${Math.floor(value/60)}:${String(value%60).padStart(2,"0")}`};
const micIsActive = mic => mic.online===true&&Number.isFinite(Number(mic.battery_percent));
const micHealth = mic => !micIsActive(mic)||Number(mic.battery_percent)<5?"critical":Number(mic.battery_percent)<=10?"low":"healthy";
const micMeters = mic => `<div class="meters">${[["BAT",mic.battery_percent],["RF",mic.rf],["AUD",mic.audio]].map(([label,value])=>`<div><div class="meter-label"><span>${label}</span><span>${value||0}%</span></div><div class="meter-track"><div class="meter-fill" style="width:${value||0}%"></div></div></div>`).join("")}</div>`;
const positionNameFromKey = key => String(key||"").split("::").at(-1).replace(/\b\w/g,letter=>letter.toUpperCase())||"Position";
const assignmentEntries = (settings,state) => {
  const selectedKeys=[...new Set(settings.position_keys||[])],labels=settings.position_labels||{},teamIds=new Set((settings.team_ids||[]).map(String)),people=state.people||[],mics=state.mics||[];
  const peopleByKey=new Map(people.filter(person=>person.position_key).map(person=>[person.position_key,person]));
  const micByKey=new Map(mics.filter(mic=>mic.assignment?.position_key).map(mic=>[mic.assignment.position_key,mic]));
  let keys=selectedKeys;
  if(!keys.length)keys=[...new Set([...people.map(person=>person.position_key),...mics.map(mic=>mic.assignment?.position_key)].filter(Boolean).filter(key=>!teamIds.size||teamIds.has(String(key).split("::")[0])))];
  if(!keys.length)return mics.filter(mic=>!teamIds.size||teamIds.has(String(mic.assignment?.team_id||"")));
  return keys.map(key=>{
    const meta=labels[key]||{},person=peopleByKey.get(key),positionName=meta.name||person?.position||positionNameFromKey(key),teamId=meta.team_id||person?.team_id||String(key).split("::")[0],teamName=meta.team_name||person?.team_name||"",matchingMic=micByKey.get(key)||mics.find(mic=>String(mic.assignment?.position||"").trim().toLocaleLowerCase()===String(positionName).trim().toLocaleLowerCase());
    const existing=matchingMic?.assignment||{},assignment={...meta,...existing,...person,position:positionName,position_key:key,team_id:teamId,team_name:teamName,name:person?.name||"Unassigned",photo:person?.photo||""};
    return matchingMic?{...matchingMic,assignment}:{id:`position-${key}`,name:"No mic",receiver:"No mic assigned",channel:"—",battery_percent:0,rf:0,audio:0,online:false,errors:["No microphone assigned"],placeholder:true,assignment};
  });
};
const filteredPeople = (settings,state) => {
  const people=state.people||[],selectedKeys=[...new Set(settings.position_keys||[])],teamIds=new Set((settings.team_ids||[]).map(String));
  if(selectedKeys.length){const keyed=new Map();for(const person of people){if(person.position_key&&!keyed.has(person.position_key))keyed.set(person.position_key,person)}return selectedKeys.flatMap(key=>keyed.has(key)?[keyed.get(key)]:[])}
  return people.filter(person=>!teamIds.size||teamIds.has(String(person.team_id||"")));
};
const normalized = value => String(value||"").trim().toLocaleLowerCase();
const presentationDisplayTitle = pp => {
  const planningTitle=String(pp.planning_center_item_title||(pp.service_item_is_pco?pp.service_item_title:"")||"").trim(),propresenterTitle=String(pp.title||pp.presentation?.name||pp.presentation?.id?.name||"").trim();
  if(planningTitle&&propresenterTitle&&normalized(planningTitle)!==normalized(propresenterTitle))return`${planningTitle} [${propresenterTitle}]`;
  return planningTitle||propresenterTitle||"No active item";
};
const isOrderHeader = item => normalized(item?.item_type)==="header";
const visibleOrderItems = (items,currentId,requestedLimit) => {
  const limit=Math.max(6,Number(requestedLimit)||6),currentIndex=items.findIndex(item=>String(item.id)===String(currentId));
  if(currentIndex<0)return items.slice(0,limit);
  const previousSlots=Math.min(2,currentIndex),start=currentIndex-previousSlots;let end=Math.min(items.length,Math.max(start+limit,currentIndex+1));
  while(end<items.length&&items.slice(currentIndex+1,end).filter(item=>!isOrderHeader(item)).length<3)end++;
  return items.slice(start,end);
};
const itemLeaderDetails = (item,state) => {
  const leader=String(item.leader||item.song_leader||item.item_leader||"").replace(/<[^>]+>/g," ").replace(/\s+/g," ").trim();
  const people=state.people||[],mics=state.mics||[],leaderIds=new Set((item.leader_person_ids||[]).map(String)),leaderKey=normalized(leader);
  let person=people.find(candidate=>leaderIds.has(String(candidate.person_id||candidate.id)));
  if(!person&&leader)person=people.find(candidate=>normalized(candidate.name)===leaderKey)||people.find(candidate=>normalized(candidate.position)===leaderKey)||people.find(candidate=>{const name=normalized(candidate.name);return name.length>=4&&(leaderKey.includes(name)||name.includes(leaderKey))});
  if(!leader&&!person)return null;
  const personIds=new Set([...leaderIds,String(person?.person_id||""),String(person?.id||"")].filter(Boolean));
  const mic=mics.find(candidate=>personIds.has(String(candidate.assignment?.person_id||""))||personIds.has(String(candidate.assignment?.id||"")))||mics.find(candidate=>normalized(candidate.assignment?.name)===normalized(person?.name||leader))||mics.find(candidate=>normalized(candidate.assignment?.position_key)===normalized(person?.position_key));
  return {name:person?.name||leader,mic:mic?.name||mic?.receiver||""};
};
const orderLeaderMarkup = (item,state,settings) => {
  if(!settings.show_leader)return"";
  const leader=itemLeaderDetails(item,state);
  if(!leader)return"";
  return `<small class="order-leader"><span>Led by ${escapeHtml(leader.name)}</span>${settings.show_mic?`<em>${leader.mic?escapeHtml(leader.mic):"No mic assigned"}</em>`:""}</small>`;
};
const formatClockTime = (value,timeZone) => {if(!value)return"—";try{return new Intl.DateTimeFormat([],{hour:"numeric",minute:"2-digit",timeZone:timeZone||undefined}).format(new Date(value))}catch(error){return new Intl.DateTimeFormat([],{hour:"numeric",minute:"2-digit"}).format(new Date(value))}};
const formatItemLength = seconds => {const value=Math.max(0,Math.round(Number(seconds)||0));return`${Math.floor(value/60)}:${String(value%60).padStart(2,"0")}`};
const estimatedItemTime = (item,timing,state) => {const start=Date.parse(timing.service_start_at||"");if(!Number.isFinite(start))return"—";const adjusting=["running","live","controlled"].includes(timing.state),drift=adjusting?Number(timing.overall_delta||0):0;return formatClockTime(new Date(start+(Number(item.starts_after)||0)*1000+drift*1000),state.timezone)};
const micCardMarkup = (mic,mode="photos",options={}) => {
  const person=mic.assignment||{},health=micHealth(mic),active=micIsActive(mic),displayName=person.name&&person.name!=="Position unfilled"?person.name:"Unassigned",position=[person.team_name,person.position].filter(Boolean).join(" · ")||"Unmapped position",numericChannel=Number(mic.channel),channel=Number.isFinite(numericChannel)?String(numericChannel).padStart(2,"0"):"—",status=mic.placeholder?"NO MIC":active?`${mic.battery_percent||0}% BAT`:"OFFLINE",hardware=mic.placeholder?"No microphone assigned":[mic.receiver,`Ch ${mic.channel}`].filter(Boolean).join(" · ");
  if(mode==="technical")return `<article class="mic-card technical-tile ${health} ${mic.placeholder?"no-mic":""}"><div class="technical-header"><div><strong>${escapeHtml(mic.name||"Mic")}</strong><span>${escapeHtml(position)}</span></div><b>${status}</b></div><div class="technical-person">${escapeHtml(displayName)}</div><div class="technical-stats">${[["Battery",mic.battery_percent],["RF",mic.rf],["Audio",mic.audio]].map(([label,value])=>`<div><span>${label}</span><strong>${value||0}%</strong></div>`).join("")}</div><div class="technical-meta">${escapeHtml(hardware)}${mic.frequency?` · ${escapeHtml(mic.frequency)}`:""}${mic.tx_type?` · ${escapeHtml(mic.tx_type)}`:""}</div>${mic.errors?.length?`<div class="technical-error">${escapeHtml(mic.errors[0])}</div>`:""}</article>`;
  const customIcon=displayName==="Unassigned"?String(options.unassignedIcon||""):"",portrait=person.photo?`<img src="${escapeHtml(person.photo)}" alt="${escapeHtml(displayName)}">`:customIcon?`<img class="unassigned-custom-icon" src="${escapeHtml(customIcon)}" alt="Unassigned">`:displayName==="Unassigned"?`<div class="talent-photo-placeholder"><span class="unassigned-board-icon" role="img" aria-label="Unassigned"></span></div>`:`<div class="talent-photo-placeholder"><span>${initials(displayName)}</span></div>`;
  return `<article class="mic-card talent-tile ${health} ${person.photo?"has-photo":""} ${mic.placeholder?"no-mic":""}"><div class="talent-media">${portrait}</div><div class="talent-gradient"></div><div class="talent-channel"><strong>${channel}</strong><em>${escapeHtml(mic.name||"Mic")}</em><span>${status}</span></div><div class="talent-identity"><div class="mic-person">${escapeHtml(displayName)}</div><div class="mic-position">${escapeHtml(position)}</div><div class="mic-hardware">${escapeHtml(hardware)}</div></div>${micMeters(mic)}</article>`;
};
const resizeMicCards = root => root.querySelectorAll(".mic-card").forEach(card=>{const rect=card.getBoundingClientRect();card.classList.toggle("mic-compact",rect.height<190||rect.width<140);card.classList.toggle("mic-micro",rect.height<125||rect.width<105)});
const resizeWidgets = root => root.querySelectorAll(".widget").forEach(widget=>{const rect=widget.getBoundingClientRect();widget.classList.toggle("widget-compact",rect.height<150);widget.classList.toggle("widget-micro",rect.height<105);widget.classList.toggle("widget-slide-compact",widget.dataset.widgetType==="slides"&&rect.height<210);widget.classList.toggle("widget-narrow",rect.width<120)});
const fitWidgetText = root => root.querySelectorAll("[data-fit-widget-text]").forEach(element=>{
  element.style.fontSize="";
  const parent=element.parentElement,max=Math.max(8,parseFloat(getComputedStyle(element).fontSize)||16);
  if(!parent.clientWidth||!parent.clientHeight)return;
  let low=7,high=Math.floor(max),best=7;
  while(low<=high){const size=Math.floor((low+high)/2);element.style.fontSize=`${size}px`;const fitsWidth=element.scrollWidth<=parent.clientWidth+1,fitsHeight=parent.scrollHeight<=parent.clientHeight+1;if(fitsWidth&&fitsHeight){best=size;low=size+1}else high=size-1}
  element.style.fontSize=`${best}px`;
});
const fitPeopleText = root => root.querySelectorAll("[data-fit-person]").forEach(copy=>{
  copy.style.removeProperty("--people-font-size");const lines=[...copy.children];if(!copy.clientWidth||!lines.length)return;
  const initial=Math.max(...lines.map(line=>parseFloat(getComputedStyle(line).fontSize)||16));let low=3,high=Math.max(3,Math.floor(initial)),best=3;
  while(low<=high){const size=Math.floor((low+high)/2);copy.style.setProperty("--people-font-size",`${size}px`);if(lines.every(line=>line.scrollWidth<=copy.clientWidth+1)){best=size;low=size+1}else high=size-1}
  copy.style.setProperty("--people-font-size",`${best}px`);
});
const resizeDashboardContent = root => {resizeWidgets(root);resizeMicCards(root);fitWidgetText(root);fitPeopleText(root);if(typeof fitOrderService==="function")fitOrderService(root)};
const enhanceDynamicContent = (root=document) => {
  root.querySelectorAll(".slide-image").forEach(image=>image.addEventListener("error",()=>image.remove(),{once:true}));
  requestAnimationFrame(()=>root.querySelectorAll("[data-fit-slide]").forEach(element=>{
    const box=element.parentElement;if(!box.clientWidth||!box.clientHeight)return;
    let low=8,high=Math.max(8,Math.min(34,Math.floor(box.clientWidth/10))),best=8;
    while(low<=high){const size=Math.floor((low+high)/2);element.style.fontSize=`${size}px`;if(element.scrollHeight<=box.clientHeight&&element.scrollWidth<=box.clientWidth){best=size;low=size+1}else high=size-1}
    element.style.fontSize=`${best}px`;
  }));requestAnimationFrame(()=>resizeDashboardContent(root));
  if(!root._churchBoardResizeObserver&&window.ResizeObserver){root._churchBoardResizeObserver=new ResizeObserver(()=>resizeDashboardContent(root));root._churchBoardResizeObserver.observe(root)}
};
const widgetNames = {clock:"Clock",service:"Service",timing:"Timers",assignments:"Scheduled Positions & Mics",mics:"Scheduled Positions & Mics",slides:"ProPresenter slides",notes:"Slide notes",order:"Order of service",people:"Team members",spl:"Audio / SPL meter",controls:"Service controls",person:"Scheduled person",text:"Custom text"};
const widgetMarkup = (widget, state) => {
  const settings=widget.settings||{}, service=state.service||{}, timing=state.timing||{}, pp=state.propresenter||{};
  let content="";
  if(widget.type==="clock") content=`<div class="clock-value" data-clock data-fit-widget-text></div><div class="clock-date" data-date></div>`;
  if(widget.type==="service") { const timingLabel=timing.source==="planning_center_live"?"Planning Center LIVE":timing.state||"scheduled";content=service.id?`<div class="service-name" data-fit-widget-text>${escapeHtml(service.title||service.service_type_name)}</div><div class="service-meta">${escapeHtml(service.dates||"")} · ${escapeHtml(timingLabel)}</div>`:`<div class="empty">No service is active</div>`; }
  if(widget.type==="timing") { const item=timing.current_item,rehearsal=timing.rehearsal===true; content=`<div class="timing-grid ${rehearsal?"rehearsal":""}">${rehearsal?'<div class="timing-mode">REHEARSAL TIMING</div>':""}<div class="timing-cell"><div class="timing-label">${escapeHtml(item?.title||"Current item")}</div><div class="timing-value ${(timing.item_delta||0)>0?"over":"ahead"}" data-fit-widget-text>${formatDuration(timing.item_delta||0)}</div></div><div class="timing-cell"><div class="timing-label">Overall</div><div class="timing-value ${(timing.overall_delta||0)>0?"over":"ahead"}" data-fit-widget-text>${formatDuration(timing.overall_delta||0)}</div></div></div>`; }
  if(["assignments","mics"].includes(widget.type)) { const mode=settings.display_mode==="technical"?"technical":"photos",mics=assignmentEntries(settings,state).slice(0,10),mediaTitle=String(settings.unassigned_media_title||"Icon").trim(),media=state.planning_center_media?.by_title?.[normalized(mediaTitle)]||state.planning_center_media?.icon,unassignedIcon=settings.use_planning_center_icon?media?.image_url||"":""; content=mics.length?`<div class="mic-list mode-${mode}">${mics.map(mic=>micCardMarkup(mic,mode,{unassignedIcon})).join("")}</div>`:`<div class="empty">Choose positions in the dashboard editor</div>`; }
  if(widget.type==="slides") { const current=pp.current||{},next=pp.next||{},title=presentationDisplayTitle(pp),showCurrent=settings.show_current!==false,showNext=settings.show_next!==false,previewsOnly=settings.slide_layout==="previews_only",showParts=!previewsOnly&&settings.show_parts!==false,mode=settings.slide_mode==="text"?"text":"image",previews=[],parts=[];if(showCurrent){previews.push(slidePreview(current,"Now",{notes:!previewsOnly&&settings.show_notes!==false,mode,showLabel:!previewsOnly}));if(showParts)parts.push(partBug(current,"Now"))}if(showNext){previews.push(slidePreview(next,"Next",{mode,showLabel:!previewsOnly}));if(showParts)parts.push(partBug(next,"Next"))}const countSlide=showCurrent?current:showNext?next:current,countTotal=Number(countSlide.total)||0,slideCount=settings.show_slide_count&&countTotal?`<div class="pro-slide-count" data-fit-widget-text>Slide ${Number(countSlide.index)||"–"} of ${countTotal}</div>`:"",header=previewsOnly?"":`<div class="pro-header"><div class="pro-title" data-fit-widget-text>${escapeHtml(title)}</div>${slideCount}</div>`,partStrip=showParts&&parts.length?`<div class="part-strip">${parts.join("")}</div>`:"";content=`<div class="pro-layout ${previewsOnly?"previews-only ":""}${!partStrip?"no-parts ":""}${previews.length===1?"one-preview":previews.length===0?"no-preview":""}">${header}${previews.length?`<div class="slide-stack">${previews.join("")}</div>${partStrip}`:`<div class="pro-hidden-message">Slide previews hidden</div>`}</div>`; }
  if(widget.type==="notes") content=`<div class="slide-notes custom-text">${escapeHtml(pp.current?.notes||"No slide notes")}</div>`;
  if(widget.type==="order") { const items=timing.service_items||service.items||[],current=timing.current_item?.id,visibleItems=visibleOrderItems(items,current,settings.limit);const serviceClock=formatClockTime(timing.service_start_at||service.starts_at,state.timezone),serviceNumber=Number(timing.service_time_count)>1?`Service ${Number(timing.service_time_index)||1} of ${Number(timing.service_time_count)}`:"Service",adjusting=["running","live","controlled"].includes(timing.state),drift=Number(timing.overall_delta||0),driftLabel=adjusting&&Math.abs(drift)>=30?`${formatDuration(drift)} ${drift>0?"late":"early"}`:"On time";content=items.length?`<div class="order-layout"><div class="order-service-time"><strong>${escapeHtml(serviceClock)}</strong><span>${escapeHtml(serviceNumber)} · <em data-order-drift>${escapeHtml(driftLabel)}</em></span></div><ol class="order-list">${visibleItems.map(item=>{const active=String(item.id)===String(current),header=isOrderHeader(item),detail=header?"":orderLeaderMarkup(item,state,settings),estimate=estimatedItemTime(item,timing,state);return`<li class="${active?"active ":""}${header?"order-header":"order-item"}"${active?' aria-current="step"':""}><span class="order-marker">${active&&!header?"▶":""}</span><span class="order-main"><b>${escapeHtml(item.title)}</b>${detail}</span>${header?"":`<span class="order-duration"><strong>${formatItemLength(item.length)}</strong><small>DURATION</small></span><span class="order-eta"><strong data-order-eta data-starts-after="${Number(item.starts_after)||0}">${escapeHtml(estimate)}</strong><small>EST</small></span>`}</li>`}).join("")}</ol></div>`:`<div class="empty">No service items</div>`; }
  if(widget.type==="people") { const people=filteredPeople(settings,state);content=people.length?`<div class="people-list">${people.map(person=>`<div class="people-row"><div class="people-avatar">${person.photo?`<img src="${escapeHtml(person.photo)}" alt="">`:`<span>${initials(person.name)}</span>`}</div><div class="people-copy" data-fit-person><strong>${escapeHtml(person.name||"Unassigned")}</strong><span>${escapeHtml([person.position,person.team_name].filter(Boolean).join(" · "))}</span></div></div>`).join("")}</div>`:`<div class="empty">No scheduled people match these filters</div>`; }
  if(widget.type==="spl") {
    const green=Number(settings.green_max??75),orange=Number(settings.orange_max??85),calibration=Number(settings.calibration_offset??100),source=settings.source||"open_sound_meter",metric=settings.metric||"laeq",response=settings.response||"fast";
    const osm=state.open_sound_meter||{};
    const isOsm=source==="open_sound_meter";
    let displayValue="--",unit="dBA",statusText="Microphone permission required",levelClass="",secondaryHtml="";
    if(isOsm) {
      unit = metric==="lceq"?"dBC":metric==="lzeq"?"dBZ":metric==="peak"?"dB Peak":"dBA";
      const rawVal = metric==="lceq"?osm.lceq:metric==="lzeq"?osm.lzeq:metric==="peak"?(osm.lpeak||osm.peak):(osm.laeq||osm.spl);
      if(osm.connected && rawVal!=null) {
        displayValue = Number(rawVal).toFixed(1);
        const val = Number(rawVal);
        levelClass = val>orange?"spl-red":val>green?"spl-orange":"spl-green";
        statusText = osm.status || `Connected to Open Sound Meter at ${osm.host||"127.0.0.1"}:${osm.port||10010}`;
      } else {
        statusText = osm.status || "Connecting to Open Sound Meter...";
      }
      const secLCeq = osm.lceq!=null?`LCeq ${Number(osm.lceq).toFixed(1)} dBC`:null;
      const secPeak = (osm.lpeak||osm.peak)!=null?`Peak ${Number(osm.lpeak||osm.peak).toFixed(1)} dB`:null;
      const secResp = osm.response?`Resp ${osm.response}`:null;
      const secondaryList = [secLCeq,secPeak,secResp].filter(Boolean);
      if(secondaryList.length) secondaryHtml = `<div class="spl-secondary-grid">${secondaryList.map(s=>`<span>${escapeHtml(s)}</span>`).join("")}</div>`;
    }
    const sourceBadge = `<span class="spl-source-badge">${isOsm?"OSM API":"MIC"}</span>`;
    content=`<div class="spl-meter ${levelClass}" data-spl-meter data-source="${source}" data-metric="${metric}" data-response="${response}" data-green="${green}" data-orange="${orange}" data-calibration="${calibration}" data-auto="${settings.auto_start===true}"><div class="spl-top-bar">${sourceBadge}<span class="spl-metric-tag">${escapeHtml(unit)} (${escapeHtml(metric.toUpperCase())})</span></div><div class="spl-reading"><strong data-spl-value>${displayValue}</strong><span>${escapeHtml(unit)}</span></div>${secondaryHtml}<div class="spl-scale"><span>Green ≤ ${green}</span><span>Orange ≤ ${orange}</span><span>Red &gt; ${orange}</span></div>${!isOsm?'<button class="spl-start" type="button" data-spl-start>Enable microphone</button>':""}<div class="spl-status" data-spl-status>${escapeHtml(statusText)}</div></div>`;
  }
  if(widget.type==="controls") { const control=state.service_control||{},pcLive=state.planning_center_live||{},item=timing.current_item||{},isControlling=pcLive.enabled?!!pcLive.has_control:!!control.active,controlLabel=pcLive.enabled?"ProPresenter → Services LIVE":control.active?"Local control":"Following schedule",statusMessage=pcLive.enabled?pcLive.message||"":"";content=`<div class="service-controls"><div class="control-now"><span>${escapeHtml(controlLabel)}</span><strong>${escapeHtml(item.title||"No current item")}</strong></div><div class="control-buttons"><button type="button" data-service-action="previous" aria-label="Previous service item">◀ Previous</button><button type="button" data-service-action="${isControlling?"release":"take"}" class="take-control">${isControlling?"Release":"Take control"}</button><button type="button" data-service-action="next" aria-label="Next service item">Next ▶</button></div><div class="control-status" data-control-status>${escapeHtml(statusMessage)}</div></div>`; }
  if(widget.type==="person") { const person=(state.people||[]).find(p=>p.position===settings.position); content=person?`<div class="person-card"><div class="avatar">${person.photo?`<img src="${escapeHtml(person.photo)}" alt="">`:initials(person.name)}</div><div><div class="person-name">${escapeHtml(person.name)}</div><div class="mic-position">${escapeHtml(person.position)}</div></div></div>`:`<div class="empty">Choose a Planning Center position in the editor</div>`; }
  if(widget.type==="text") content=`<div class="custom-text">${escapeHtml(settings.text||"Custom text")}</div>`;
  const hideTitle=settings.show_title===false||(widget.type==="slides"&&settings.slide_layout==="previews_only");
  return `<section class="widget ${hideTitle?"widget-title-hidden":""}" data-widget="${escapeHtml(widget.id)}" data-widget-type="${escapeHtml(widget.type)}" style="grid-column:${widget.x+1}/span ${widget.w};grid-row:${widget.y+1}/span ${widget.h}"><div class="widget-heading">${escapeHtml(widget.title||widgetNames[widget.type])}</div><div class="widget-body">${content}</div></section>`;
};
let lastClockFitMinute="";
const tickClocks = () => { const now=new Date(),time=now.toLocaleTimeString([],{hour:"numeric",minute:"2-digit",second:"2-digit"}),date=now.toLocaleDateString([],{weekday:"long",month:"long",day:"numeric"}),fitMinute=`${now.getHours()}:${now.getMinutes()}`;document.querySelectorAll("[data-clock]").forEach(el=>{if(el.textContent!==time)el.textContent=time});document.querySelectorAll("[data-date]").forEach(el=>{if(el.textContent!==date)el.textContent=date});if(fitMinute!==lastClockFitMinute){lastClockFitMinute=fitMinute;requestAnimationFrame(()=>fitWidgetText(document))} };
