let moduleItems=[];
let selectedModule=null;

const iconFor=module=>({Core:"▦","Planning & people":"P",Presentation:"▶",Interactions:"↔","Wireless audio":"⌁","Audio measurement":"dB",Streaming:"●",Video:"▣",Producer:"P"})[module.category]||"＋";
const moduleById=id=>moduleItems.find(module=>module.id===id);

async function loadModules(message=""){
  try{
    const result=await api("/api/modules");
    moduleItems=result.items||[];
    renderModuleFilters();
    renderModules();
    if(message)document.querySelector("#module-status").textContent=message;
  }catch(error){
    if(/sign|unauthorized|401/i.test(error.message)){location.href="/login?next=%2Fmodules";return}
    document.querySelector("#module-status").textContent=error.message;
  }
}

function renderModuleFilters(){
  const select=document.querySelector("#module-category"),current=select.value;
  const categories=[...new Set(moduleItems.map(module=>module.category))].sort();
  select.innerHTML='<option value="">All categories</option>'+categories.map(category=>`<option>${escapeHtml(category)}</option>`).join("");
  select.value=current;
  const count=moduleItems.filter(module=>module.installed&&module.enabled).length;
  document.querySelector("#module-summary").innerHTML=`<strong>${count}</strong><span>modules installed</span>`;
}

function filteredModules(){
  const term=document.querySelector("#module-search").value.trim().toLocaleLowerCase();
  const category=document.querySelector("#module-category").value;
  const installedOnly=document.querySelector("#module-installed-only").checked;
  return moduleItems.filter(module=>(!term||`${module.name} ${module.vendor} ${module.description} ${module.category}`.toLocaleLowerCase().includes(term))&&(!category||module.category===category)&&(!installedOnly||module.installed));
}

function renderModules(){
  const modules=filteredModules(),groups=new Map();
  for(const module of modules){const items=groups.get(module.category)||[];items.push(module);groups.set(module.category,items)}
  document.querySelector("#module-groups").innerHTML=[...groups.entries()].map(([category,items])=>`<section class="module-group"><h2>${escapeHtml(category)}</h2><div class="module-grid">${items.map(moduleCard).join("")}</div></section>`).join("")||'<p class="muted">No modules match these filters.</p>';
}

function moduleCard(module){
  const dependencies=(module.dependencies||[]).map(id=>moduleById(id)?.name||id);
  const state=module.update_available?'<span class="module-badge update">Update</span>':module.installed?'<span class="module-badge live">Installed</span>':'<span class="module-badge">Available</span>';
  const action=module.installed?(module.update_available?`<button class="button" data-module-update="${escapeHtml(module.id)}">Update</button>`:`<button class="button secondary" data-module-open="${escapeHtml(module.id)}">Manage</button>`):`<button class="button" data-module-install="${escapeHtml(module.id)}">Add module</button>`;
  return `<article class="module-card ${module.installed?"installed":""} ${module.update_available?"update":""}"><div class="module-card-header"><span class="module-card-icon">${escapeHtml(iconFor(module))}</span><div><h3>${escapeHtml(module.name)}</h3><span class="module-card-vendor">${escapeHtml(module.vendor)} · ${escapeHtml(module.available_version)}</span></div><div class="module-badges">${state}</div></div><p>${escapeHtml(module.description)}</p><div class="module-dependency-note">${dependencies.length?`Adds: ${escapeHtml(dependencies.join(", "))}`:`${(module.widgets||[]).length} widget${(module.widgets||[]).length===1?"":"s"} · ${(module.pages||[]).length} page${(module.pages||[]).length===1?"":"s"}`}</div><div class="module-card-actions"><button class="button secondary" data-module-open="${escapeHtml(module.id)}">Details</button>${action}</div></article>`;
}

async function openModule(moduleId){
  selectedModule=moduleById(moduleId);if(!selectedModule)return;
  const module=selectedModule,dialog=document.querySelector("#module-details"),dependencies=(module.dependencies||[]).map(id=>moduleById(id)?.name||id);
  document.querySelector("#module-detail-vendor").textContent=`${module.vendor} · ${module.available_version}`;
  document.querySelector("#module-detail-name").textContent=module.name;
  document.querySelector("#module-detail-description").textContent=module.description;
  document.querySelector("#module-detail-dependencies").innerHTML=dependencies.length?`<p class="module-dependency-note"><strong>Required modules:</strong> ${escapeHtml(dependencies.join(", "))}. They are installed automatically.</p>`:'<p class="module-dependency-note">This module has no required modules.</p>';
  document.querySelector("#module-detail-setup").innerHTML=(module.setup||[]).map(step=>`<li><strong>${escapeHtml(step.title)}</strong><span>${escapeHtml(step.text)}${step.url?` <a href="${escapeHtml(step.url)}" target="_blank" rel="noreferrer">Open official download</a>`:""}</span></li>`).join("")||'<li>No additional setup is required.</li>';
  const contracts=[...(module.provides||[]).map(value=>`Provides ${value}`),...(module.consumes||[]).map(value=>`Uses ${value}`)];
  document.querySelector("#module-detail-contracts").innerHTML=contracts.map(value=>`<code>${escapeHtml(value)}</code>`).join("");
  document.querySelector("#module-detail-contracts-section").hidden=!contracts.length;
  const capabilities=[...(module.pages||[]).map(page=>`Page · ${page.name}`),...(module.widgets||[]).map(widget=>`Widget · ${widget.name}`)];
  document.querySelector("#module-detail-widgets").innerHTML=capabilities.map(value=>`<span>${escapeHtml(value)}</span>`).join("");
  document.querySelector("#module-detail-widgets-section").hidden=!capabilities.length;
  const configure=module.installed?"":"";
  const update=module.update_available?`<button class="button" data-module-update="${escapeHtml(module.id)}">Update to ${escapeHtml(module.available_version)}</button>`:"";
  const install=!module.installed?`<button class="button" data-module-install="${escapeHtml(module.id)}">Add module${dependencies.length?" and requirements":""}</button>`:"";
  const remove=module.installed&&!module.core?`<button class="button danger module-danger" data-module-remove="${escapeHtml(module.id)}">Remove</button>`:"";
  const policy=module.installed&&!module.core?`<label class="module-auto-update"><input type="checkbox" data-module-auto-update="${escapeHtml(module.id)}" ${module.auto_update?"checked":""}>Automatically apply bundled module updates</label>`:"";
  document.querySelector("#module-detail-actions").innerHTML=`${remove}${policy}${configure}${update}${install}<button class="button secondary" data-module-close>Done</button>`;
  const configuration=document.querySelector("#module-detail-configuration");
  configuration.hidden=!module.installed;
  if(module.installed)await window.ModuleSettings?.open(module);
  dialog.showModal();
  history.replaceState(null,"",`#${encodeURIComponent(module.id)}`);
}

async function moduleAction(moduleId,action,options={}){
  const status=document.querySelector("#module-status"),module=moduleById(moduleId);status.textContent=`${action==="install"?"Adding":action==="update"?"Updating":"Removing"} ${module?.name||moduleId}…`;
  try{
    await api(`/api/modules/${encodeURIComponent(moduleId)}${action==="remove"?"":`/${action}`}`,{method:action==="remove"?"DELETE":"POST",...options});
    if(document.querySelector("#module-details").open)document.querySelector("#module-details").close();
    await loadModules(`${module?.name||moduleId} ${action==="remove"?"removed":action==="update"?"updated":"added"}.`);
  }catch(error){status.textContent=error.message}
}

document.addEventListener("click",event=>{
  const open=event.target.closest("[data-module-open]"),install=event.target.closest("[data-module-install]"),update=event.target.closest("[data-module-update]"),remove=event.target.closest("[data-module-remove]");
  if(open)openModule(open.dataset.moduleOpen);
  if(install)moduleAction(install.dataset.moduleInstall,"install");
  if(update)moduleAction(update.dataset.moduleUpdate,"update");
  if(remove&&confirm(`Remove ${moduleById(remove.dataset.moduleRemove)?.name||"this module"}? Existing page widgets remain in the layout but the integration will be disabled.`))moduleAction(remove.dataset.moduleRemove,"remove");
  if(event.target.closest("[data-module-close]"))document.querySelector("#module-details").close();
});
document.addEventListener("change",async event=>{const policy=event.target.closest("[data-module-auto-update]");if(!policy)return;try{await api(`/api/modules/${encodeURIComponent(policy.dataset.moduleAutoUpdate)}/policy`,{method:"PUT",body:JSON.stringify({auto_update:policy.checked})});await loadModules()}catch(error){document.querySelector("#module-status").textContent=error.message}});
for(const id of ["module-search","module-category","module-installed-only"])document.querySelector(`#${id}`).addEventListener(id==="module-search"?"input":"change",renderModules);
document.querySelector("#module-refresh").onclick=()=>loadModules("Module catalog checked. Installed modules are current when no update badge appears.");
function closeModuleDialog(){document.querySelector("#module-details").close();history.replaceState(null,"",location.pathname+location.search)}
document.querySelector("#module-detail-close").onclick=closeModuleDialog;
document.querySelector("#module-details").addEventListener("close",()=>{if(location.hash)history.replaceState(null,"",location.pathname+location.search)});
loadModules().then(()=>{const requested=decodeURIComponent(location.hash.slice(1));if(requested&&moduleById(requested))openModule(requested)});
