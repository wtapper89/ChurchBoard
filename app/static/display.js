let dashboard,lastState={},serverInstance="",refreshInFlight=false,planOptionsKey="",planSelectionInFlight=false,lastFullRefresh=0,compactEtag="";
const widgetRenderKeys=new Map();
const objectIds=new WeakMap();let nextObjectId=1;
const slug=decodeURIComponent(location.pathname.split("/").pop());
const splEngine={context:null,analyser:null,bins:null,stream:null,running:false,autoAttempted:false,rawDb:null};
const aWeighting=frequency=>{if(frequency<=0)return-120;const f2=frequency*frequency,numerator=(12200**2)*(f2**2),denominator=(f2+20.6**2)*Math.sqrt((f2+107.7**2)*(f2+737.9**2))*(f2+12200**2);return 20*Math.log10(numerator/denominator)+2};
function setSplStatus(message){document.querySelectorAll("[data-spl-status]").forEach(element=>element.textContent=message)}
async function startSpl(){
  if(splEngine.running){if(splEngine.context?.state==="suspended")await splEngine.context.resume();return}
  if(!navigator.mediaDevices?.getUserMedia){setSplStatus("Microphone input is not supported in this browser");return}
  try{
    splEngine.stream=await navigator.mediaDevices.getUserMedia({audio:{autoGainControl:false,echoCancellation:false,noiseSuppression:false}});splEngine.context=new(window.AudioContext||window.webkitAudioContext)();const source=splEngine.context.createMediaStreamSource(splEngine.stream);splEngine.analyser=splEngine.context.createAnalyser();splEngine.analyser.fftSize=4096;splEngine.analyser.smoothingTimeConstant=.72;splEngine.bins=new Float32Array(splEngine.analyser.frequencyBinCount);source.connect(splEngine.analyser);splEngine.running=true;setSplStatus("Live A-weighted microphone level");requestAnimationFrame(updateSpl)
  }catch(error){setSplStatus(error.name==="NotAllowedError"?"Microphone permission was denied":"Could not open the microphone")}
}
function updateSpl(){
  if(!splEngine.running)return;splEngine.analyser.getFloatFrequencyData(splEngine.bins);let weightedPower=0;const binWidth=splEngine.context.sampleRate/splEngine.analyser.fftSize;
  for(let index=1;index<splEngine.bins.length;index++){const db=splEngine.bins[index];if(Number.isFinite(db))weightedPower+=10**((db+aWeighting(index*binWidth))/10)}
  const measured=weightedPower>0?10*Math.log10(weightedPower):-120;splEngine.rawDb=splEngine.rawDb===null?measured:splEngine.rawDb*.78+measured*.22;
  document.querySelectorAll("[data-spl-meter]").forEach(meter=>{const value=Math.max(0,splEngine.rawDb+Number(meter.dataset.calibration||0)),green=Number(meter.dataset.green),orange=Number(meter.dataset.orange),reading=meter.querySelector("[data-spl-value]");reading.textContent=value.toFixed(1);meter.classList.toggle("spl-green",value<=green);meter.classList.toggle("spl-orange",value>green&&value<=orange);meter.classList.toggle("spl-red",value>orange);const status=meter.querySelector("[data-spl-status]");if(status)status.textContent="Live A-weighted microphone level"});requestAnimationFrame(updateSpl)
}
function maybeAutoStartSpl(){if(splEngine.running||splEngine.autoAttempted)return;if(document.querySelector('[data-spl-meter][data-source="browser"][data-auto="true"]')){splEngine.autoAttempted=true;startSpl()}}
async function loadBoard(){
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
