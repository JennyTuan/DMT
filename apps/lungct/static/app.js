const $=id=>document.getElementById(id);
const session=await fetch('/api/session').then(r=>r.json());
const analysisModels=session.analysis_models??[];
const state={project:null,data:null,catalog:[],series:null,index:0,zoom:1,pan:[0,0],image:null,loading:true,imageIndex:null,imageSeries:null,locator:null,selected:null,findings:[],tool:null,points:[],afterSeries:[],analysisModels,modelConfigured:analysisModels.length>0};
state.reviewLayout='axial';
state.viewTool='window';

function updateReviewLayout(reviewing){
  const workstation=$('workstation'),coronal=$('coronalView');
  const compare=reviewing&&state.reviewLayout==='coronal';
  const parent=compare?$('imageViews'):workstation.querySelector('.workstationSide');
  if(coronal.parentElement!==parent){
    if(compare)parent.append(coronal);
    else parent.prepend(coronal);
  }
  coronal.hidden=reviewing&&!compare;
  workstation.dataset.reviewLayout=reviewing?state.reviewLayout:'';
  $('reviewLayouts').hidden=!reviewing;
  $('returnFinding').hidden=!reviewing;
  $('axialLayout').setAttribute('aria-pressed',String(!compare));
  $('coronalLayout').setAttribute('aria-pressed',String(compare));
  void loadVisibleLocator();
}
function updateWorkflow(){
  const stage=!$('queue').hidden?1:!$('exportPanel').hidden?4:(state.workflowStep||2),draft=state.draft,completed=draft?.status==='completed';
  const choice=state.catalog.find(d=>d.project.project_id===queueChoice?.project)?.series.find(s=>s.series_key===queueChoice?.series);
  const allowed=[true,stage===1?!!choice?.eligible:!!state.series,stage!==1&&!!draft,stage!==1&&!!completed];
  for(let i=1;i<=4;i++){const b=$('step'+i);b.classList.toggle('current',i===stage);b.classList.toggle('done',i<stage);b.disabled=!allowed[i-1];if(i===stage)b.setAttribute('aria-current','step');else b.removeAttribute('aria-current');}
  const next=$('workflowNext');next.disabled=false;
  $('analysisPanel').hidden=stage!==2;
  $('reviewPanel').hidden=stage!==3;
  if(stage!==3)state.cancelAnnotationPreview?.();
  updateReviewLayout(stage===3);
  const primaryStartsRun=stage===2&&!draft&&!state.runReady&&state.modelConfigured&&!state.runFailed;
  const primaryStartsManual=stage===2&&!draft&&!state.runReady&&!primaryStartsRun;
  $('startRun').hidden=!state.modelConfigured||primaryStartsRun;
  $('manualDraft').hidden=primaryStartsManual||!!draft&&!draft.run_id;
  if($('useRun'))$('useRun').hidden=!state.runReady||!draft||draft.run_id===state.analysisRun?.run_id;
  if(stage===1){next.textContent='进入分析 →';next.disabled=!choice?.eligible;$('workflowHint').textContent=choice?.eligible?'已选中可用序列，请进入分析':'选择病例及可用 CT 序列';}
  if(stage===2){next.textContent=state.runBusy?'分析中…':draft?'继续复核 →':state.runReady?'复核分析结果 →':state.modelConfigured&&!state.runFailed?'开始 AI 分析':'开始人工复核 →';next.disabled=!!state.runBusy;$('workflowHint').textContent=state.runBusy?'分析完成后可复核候选':state.runReady?'分析已完成，下一步逐项核对候选':state.runFailed?'分析失败，可重试或转人工复核':'选择 AI 分析或人工阅片路径';}
  if(stage===3){const pending=draft?.counts.pending||0;next.textContent=completed?'查看导出 →':'完成复核 →';next.disabled=pending>0;$('workflowHint').textContent=completed?'本例已完成，快照已冻结':pending?`还有 ${pending} 项待复核`:'逐项复核已完成';}
  if(stage===4){next.textContent=state.exportSaved?'返回病例列表':'导出研究包 →';next.disabled=!state.exportSaved&&!state.exportReady;$('workflowHint').textContent=state.exportSaved?'研究包已保存，可返回病例列表':state.exportReady?'核对纳入检查与结节数量，再保存研究包':'没有可导出的已完成快照';}
}
function setWorkflowStep(step){state.workflowStep=step;updateWorkflow();}
function message(text,error=false){$('status').textContent=text;$('status').className=error?'error':'';}
async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-LungCT-Token':session.token},body:JSON.stringify(body)}:{});const v=await r.json();if(!r.ok)throw Error(v.error);return v;}
async function act(action,args={}){return api('/api/action',{action,...args});}
function safely(fn){return async(...args)=>{try{await fn(...args);}catch(e){message(e.message,true);}};}
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
async function projects(){await refresh();$('projects').replaceChildren(new Option('选择研究项目',''),...state.catalog.map(d=>new Option(d.project.name,d.project.project_id)));$('projects').value=state.project||'';}
async function openProject(id){state.project=id;localStorage.setItem('lungct-project',id);await refresh();}
async function refresh(){const list=await api('/api/state');state.catalog=await Promise.all(list.projects.map(p=>api('/api/state?project='+p.project_id)));if(!state.catalog.some(d=>d.project.project_id===state.project)){const saved=localStorage.getItem('lungct-project');state.project=state.catalog.find(d=>d.project.project_id===saved)?.project.project_id||state.catalog.find(d=>d.studies.length)?.project.project_id||state.catalog[0]?.project.project_id||null;}state.data=state.catalog.find(d=>d.project.project_id===state.project)||null;$('projects').value=state.project||'';renderCases();}
let queueChoice=null,previewRequest=0;
const statusNames={draft:'草稿',reviewing:'复核中',completed:'已完成'};
function renderCases(){
  const filter=$('caseFilter').value.toLowerCase(),status=$('caseStatus').value,rows=[];
  for(const data of state.catalog)for(const c of data.studies){
    if(!c.case_code.toLowerCase().includes(filter)&&!data.project.name.toLowerCase().includes(filter))continue;
    if(status&&c.status!==status)continue;
    rows.push({data,case:c,series:data.series.filter(s=>s.study_key===c.study_key)});
  }
  const container=$('cases');container.replaceChildren();
  if(!rows.length){previewRequest++;queueChoice=null;container.append(el('p','暂无符合条件的病例。','emptyCases'));updateWorkflow();return;}
  const table=el('table');table.className='caseTable';const head=el('thead'),header=el('tr');
  for(const name of ['病例 / 检查','所属项目','复核状态','图像序列','数据类型'])header.append(el('th',name));
  head.append(header);table.append(head);const body=el('tbody');
  for(const item of rows){const {data,case:c,series}=item,row=el('tr');row.tabIndex=0;row.dataset.study=c.study_key;
    row.append(el('td',c.case_code),el('td',data.project.name),el('td',statusNames[c.status]),el('td',`${series.length} 个序列 · ${series.reduce((n,s)=>n+s.slice_keys.length,0)} 幅图像`),el('td',series.every(s=>s.synthetic)?'合成体模':'已登记脱敏 CT'));
    const choose=()=>{queueChoice={project:data.project.project_id,study:c.study_key,series:null};renderCases();};
    row.onclick=choose;row.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose();}};body.append(row);
  }
  table.append(body);const listViewport=el('div',undefined,'caseListViewport');listViewport.append(table);container.append(listViewport);
  const item=rows.find(r=>r.case.study_key===queueChoice?.study&&r.data.project.project_id===queueChoice?.project)||rows[0];
  const selected=item.series.find(s=>s.series_key===queueChoice?.series)||item.series.find(s=>s.eligible)||item.series[0];
  queueChoice={project:item.data.project.project_id,study:item.case.study_key,series:selected?.series_key};
  state.queueProject=queueChoice.project;
  for(const row of body.children)row.classList.toggle('selected',row.dataset.study===item.case.study_key);
  renderCasePreview(item,selected,container);updateWorkflow();
}
function renderCasePreview(item,selected,container){
  const {data,case:c,series}=item,request=++previewRequest,panel=el('section',undefined,'casePreview');panel.id='casePreview';
  const title=el('div',undefined,'previewHeading');title.append(el('strong',`${data.project.name}  /  ${c.case_code}`),el('span',`当前检查 · ${series.length} 个图像序列`));panel.append(title);
  const grid=el('div',undefined,'previewGrid'),info=el('section'),list=el('section'),image=el('section',undefined,'previewImage');
  info.append(el('h2','患者与检查信息'));const dl=el('dl');
  function field(name,value){dl.append(el('dt',name),el('dd',value||'未提供'));}
  field('受试者编号','S-'+c.subject_key.slice(-8).toUpperCase());field('姓名','已脱敏');
  field('性别','读取中…');const sexValue=dl.lastChild;field('年龄','读取中…');const ageValue=dl.lastChild;
  field('检查部位','胸部 CT');field('研究来源',({screening:'筛查',non_screening:'非筛查',unknown:'未知'})[selected?.source.research_source]);field('复核状态',statusNames[c.status]);info.append(dl);
  list.append(el('h2','当前检查的图像序列'));
  series.forEach((s,i)=>{const b=el('button',undefined,'seriesChoice'+(s.series_key===selected?.series_key?' selected':''));b.dataset.series=s.series_key;
    b.append(el('strong',`序列 ${i+1} · ${s.qc_codes.includes('LOCALIZER')?'定位像':'轴位 CT'}`),el('span',`${s.slice_keys.length} 幅 · 层厚 ${s.thickness_mm} mm`),el('small',s.eligible?'质控通过 · 可分析':s.qc_codes.includes('LOCALIZER')?'定位像 · 不用于结节分析':'质控未通过：'+s.qc_codes.join(' / ')));
    b.onclick=()=>{queueChoice.series=s.series_key;renderCases();};list.append(b);
  });
  const previewHeading=el('div',undefined,'previewImageHeading');
  previewHeading.append(el('h2','图像预览'));image.append(previewHeading);
  if(selected?.eligible){
    const viewport=el('div',undefined,'previewViewport');
    const label=el('output','正在加载…','previewSliceLabel');
    const hint=el('small','滚轮翻层','previewWheelHint');
    hint.id='previewWheelHint';
    const keys=el('span','聚焦后可用上下方向键翻层。','previewKeyboardHint');
    keys.id='previewKeyboardHint';
    viewport.tabIndex=0;
    viewport.setAttribute('role','group');
    viewport.setAttribute('aria-label','预览切片');
    viewport.setAttribute('aria-describedby','previewWheelHint previewKeyboardHint previewSliceLabel');
    label.id='previewSliceLabel';
    const metadata=el('div',undefined,'previewImageMetadata');
    metadata.append(el('small',`${selected.geometry.columns} × ${selected.geometry.rows} · ${selected.synthetic?'合成体模':'原始 CT'}`),label);
    previewHeading.append(hint,keys);
    image.append(viewport,metadata);
    const query=new URLSearchParams({project:data.project.project_id,series:selected.series_key,center:-600,width:1500});
    bindPreview(viewport,label,query,selected.slice_keys.length,()=>request===previewRequest&&!$('queue').hidden);
  }else image.append(el('div','该序列未通过分析质控，无法预览或进入。','previewUnavailable'));
  grid.append(info,list,image);panel.append(grid);container.append(panel);
  if(selected)api('/api/series-info?'+new URLSearchParams({project:data.project.project_id,series:selected.series_key})).then(v=>{if(request!==previewRequest)return;sexValue.textContent=({M:'男',F:'女',O:'其他'})[v.sex]||'未提供';const units={Y:'岁',M:'月',W:'周',D:'天'};ageValue.textContent=v.age?`${Number(v.age.slice(0,3))} ${units[v.age[3]]}`:'未提供';}).catch(()=>{if(request===previewRequest){sexValue.textContent='未提供';ageValue.textContent='未提供';}});
}
function bindPreview(viewport,label,query,total,isCurrent){
  const frames=new Map();
  let target=Math.floor(total/2),displayed=-1,direction=0;
  let loading=false,prefetching=false;

  function frame(index){
    const cached=frames.get(index);
    if(cached)return cached;
    const img=new Image();
    img.alt='所选 CT 序列切片预览';
    img.src=`/api/image?${query}&index=${index}`;
    const decoded=img.decode().then(()=>img,error=>{frames.delete(index);throw error;});
    frames.set(index,decoded);
    if(frames.size>16)frames.delete(frames.keys().next().value);
    return decoded;
  }

  async function prefetch(){
    if(prefetching)return;
    prefetching=true;
    const base=displayed;
    const offsets=direction?[direction,2*direction,-direction]:[1,-1,2,-2];
    try{
      for(const offset of offsets){
        if(!isCurrent()||target!==base)break;
        const index=base+offset;
        if(index>=0&&index<total)await frame(index).catch(()=>{});
      }
    }finally{
      prefetching=false;
      if(isCurrent()&&displayed===target&&displayed!==base)void prefetch();
    }
  }

  async function show(){
    if(loading)return;
    loading=true;
    try{
      while(isCurrent()&&target!==displayed){
        const index=target;
        let img;
        try{img=await frame(index);}
        catch{
          if(!isCurrent())return;
          if(index!==target)continue;
          if(displayed>=0)target=displayed;
          else label.textContent='预览加载失败';
          message('预览切片加载失败',true);
          return;
        }
        if(!isCurrent())return;
        // A decoded intermediate slice may advance the display, but must not overshoot a newer target.
        if(index===target||displayed<0||(index-displayed)*(target-index)>0){
          viewport.replaceChildren(img);
          displayed=index;
          label.textContent=`${index+1} / ${total}`;
        }
      }
    }finally{
      loading=false;
      if(isCurrent()&&displayed>=0&&displayed===target)void prefetch();
    }
  }

  function step(offset){
    const next=Math.max(0,Math.min(total-1,target+offset));
    if(next===target&&displayed>=0)return;
    direction=offset;
    target=next;
    void show();
  }
  viewport.addEventListener('wheel',event=>{
    if(!event.deltaY||Math.abs(event.deltaX)>Math.abs(event.deltaY)||event.ctrlKey||event.metaKey)return;
    event.preventDefault();
    step(Math.sign(event.deltaY));
  },{passive:false});
  viewport.onkeydown=event=>{
    if(event.key!=='ArrowUp'&&event.key!=='ArrowDown')return;
    event.preventDefault();
    step(event.key==='ArrowDown'?1:-1);
  };
  void show();
}
$('projectForm').onsubmit=safely(async e=>{e.preventDefault();const f=new FormData(e.target);const p=await act('createProject',{name:f.get('name'),operator:f.get('operator')});await projects(false);$('projects').value=p.project_id;await openProject(p.project_id);message('研究项目已创建');});
$('projects').onchange=safely(e=>openProject(e.target.value));
$('addCaseButton').onclick=()=>{$('addCaseDialog').showModal();document.querySelector('#importForm input[name=directory]').focus();};
$('closeAddCase').onclick=()=>$('addCaseDialog').close();
$('importForm').onsubmit=safely(async e=>{e.preventDefault();if(!state.project)throw Error('请先选择研究项目');const f=new FormData(e.target);await act('importStudy',{project:state.project,directory:f.get('directory'),source:{source_code:f.get('source_code'),research_source:f.get('research_source'),authorized:true,deidentified:true,pixels_checked:true,adult_chest:true,noncontrast:true}});await refresh();$('addCaseDialog').close();message('导入完成，请核对并确认分析序列');});
$('caseFilter').oninput=renderCases;$('caseStatus').onchange=renderCases;
$('queueButton').onclick=safely(async()=>{$('queue').hidden=false;$('workstation').hidden=true;$('exportPanel').hidden=true;$('context').hidden=true;$('queueButton').hidden=true;await refresh();});
async function openSeries(s){await ensureViewer();state.workflowStep=2;state.runReady=false;state.runBusy=false;state.runFailed=false;await act('selectSeries',{project:state.project,study:s.study_key,series:s.series_key});viewer.clear();state.series=s;state.draft=null;state.image=null;state.imageIndex=null;state.imageSeries=null;state.locator=null;displayedAxial=null;pendingLocator=null;state.loading=true;state.index=Math.floor(s.slice_keys.length/2);state.zoom=1;state.pan=[0,0];state.selected=null;state.findings=[];$('queue').hidden=true;$('context').hidden=false;$('queueButton').hidden=false;$('workstation').hidden=false;$('exportPanel').hidden=true;$('slice').max=s.slice_keys.length-1;$('slice').value=state.index;$('sliceLabel').textContent='';$('caseLabel').textContent=state.data.studies.find(c=>c.study_key===s.study_key).case_code;$('context').textContent=state.data.project.name+' / '+$('caseLabel').textContent;$('imageLabel').textContent=s.synthetic?'合成几何体模 · 不代表真实推理':'已登记脱敏原始 CT';updateReviewLayout(false);await loadImages();for(const handler of state.afterSeries)await handler();updateWorkflow();}
async function enterQueueChoice(){const data=state.catalog.find(d=>d.project.project_id===queueChoice?.project),s=data?.series.find(s=>s.series_key===queueChoice?.series);if(!s?.eligible)throw Error('请选择可用的 CT 序列');await openProject(data.project.project_id);await openSeries(s);}
$('step1').onclick=()=>$('queueButton').click();
$('step2').onclick=safely(async()=>{if(!$('queue').hidden)await enterQueueChoice();else{$('exportPanel').hidden=true;$('workstation').hidden=false;setWorkflowStep(2);}});
$('step3').onclick=()=>{$('exportPanel').hidden=true;$('workstation').hidden=false;setWorkflowStep(3);};
$('step4').onclick=()=>$('exportButton').click();
$('workflowNext').onclick=safely(async()=>{
  const stage=!$('queue').hidden?1:!$('exportPanel').hidden?4:state.workflowStep||2;
  if(stage===1)return enterQueueChoice();
  if(stage===2){if(state.draft)setWorkflowStep(3);else if(state.runReady)$('useRun').click();else if(state.modelConfigured&&!state.runFailed)$('startRun').click();else $('manualDraft').click();}
  if(stage===3){
    if(state.draft?.status==='completed')$('exportButton').click();
    else state.openCompletion?.();
  }
  if(stage===4){if(state.exportSaved)$('queueButton').click();else $('saveResearchPackage')?.click();}
});
let viewer,viewerInitialization;
function ensureViewer(){
  viewerInitialization??=import('/static/vendor/cornerstone.js').then(({createViewer})=>{viewer=createViewer();}).catch(error=>{
    viewerInitialization=null;
    if(error instanceof TypeError)throw Error('阅片组件加载失败，请检查本地 Cornerstone3D 构建');
    throw error;
  });
  return viewerInitialization;
}
let axialTask=null,pendingAxial=null,latestAxial=null,displayedAxial=null,prefetchTask=null;
let pendingLocator=null,wantedLocatorUrl=null;
let axialStack=null;
let imageWindow=[-600,1500];

function axialImage(job,index){
  const g=job.series.geometry;
  return viewer.prepare(job.imageIds[index],{
    dimensions:[g.columns,g.rows],spacing:[g.spacing[1],g.spacing[0]],
    origin:g.origins[index],direction:[...g.row,...g.column],frameOfReferenceUID:job.series.series_key,
  });
}
function prefetchAdjacent(job){
  const next=job.index+job.direction;
  if(!job.direction||next<0||next>=job.series.slice_keys.length||prefetchTask||$('workstation').hidden)return;
  prefetchTask=axialImage(job,next).catch(()=>{}).finally(()=>{prefetchTask=null;});
}
function changeImageWindow(){
  const center=$('center').valueAsNumber,width=$('width').valueAsNumber;
  if(!Number.isFinite(center)||!Number.isFinite(width)||width<=0)throw Error('窗宽窗位无效');
  imageWindow=[center,width];
  viewer?.windowImage('axial',center,width);
  viewer?.windowImage('coronal',center,width);
}
function setAxialLoading(loading){
  state.loading=loading;
  $('loadingLabel').hidden=!loading||!!state.image;
  if(loading)$('probeValue').hidden=true;
}
async function showAxial(job,image){
  await viewer.display('axial',job.imageIds,job.index,...imageWindow);
  if(job.series!==state.series)return;
  displayedAxial=job;
  state.image=image;state.imageIndex=job.index;state.imageSeries=job.series.series_key;
  $('sliceLabel').textContent=`${job.index+1} / ${job.series.slice_keys.length}`;
  const g=job.series.geometry;
  function dir(v){
    const labels=[['左 L','右 R'],['后 P','前 A'],['头 S','足 I']];
    return [0,1,2].filter(i=>Math.abs(v[i])>.2).sort((a,b)=>Math.abs(v[b])-Math.abs(v[a])).map(i=>labels[i][v[i]>0?0:1]).join(' / ');
  }
  $('leftLabel').textContent=dir(g.row.map(v=>-v));
  $('rightLabel').textContent=dir(g.row);
  $('topLabel').textContent=dir(g.column.map(v=>-v));
  draw();drawCoronal();
}
async function drainAxial(){
  try{
    while(pendingAxial){
      const job=pendingAxial;pendingAxial=null;
      try{
        const image=await axialImage(job,job.index);
        const current=job===latestAxial;
        // Paint an intermediate frame only if it advances toward the latest target.
        const advancing=displayedAxial?.scope===job.scope&&job.scope===latestAxial.scope&&
          (job.index-displayedAxial.index)*(latestAxial.index-job.index)>0;
        if(current||advancing)await showAxial(job,image);
        if(job===latestAxial){setAxialLoading(false);prefetchAdjacent(job);}
      }catch(error){
        if(job!==latestAxial)continue;
        if(state.image){state.index=state.imageIndex;$('slice').value=state.index;}
        setAxialLoading(false);
        throw error;
      }
    }
  }finally{axialTask=null;}
}
function imageStack(){
  const scope=new URLSearchParams({project:state.project,series:state.series.series_key,format:'hu'}).toString();
  if(axialStack?.scope!==scope){
    const imageIds=state.series.slice_keys.map((_,index)=>viewer.imageId(`/api/image?${scope}&index=${index}`));
    axialStack={scope,imageIds};
  }
  return axialStack;
}
function locatorScope(){
  const query=new URLSearchParams({project:state.project,series:state.series.series_key});
  const y=state.findings.find(f=>f.finding_id===state.selected)?.revision.center_lps[1];
  if(y!==undefined)query.set('y',y);
  return query;
}
async function loadLocator(){
  if(!viewer||!state.series||$('workstation').hidden||$('coronalView').hidden)return;
  const query=locatorScope(),metadataUrl='/api/locator?'+query;
  query.set('plane','coronal');query.set('format','hu');
  const url='/api/image?'+query;
  wantedLocatorUrl=url;
  if(pendingLocator?.url===url)return;
  if(state.locator?.url===url){pendingLocator=null;return;}
  const job={url},series=state.series;pendingLocator=job;
  try{
    const meta=await api(metadataUrl),id=viewer.imageId(url);
    if(pendingLocator!==job)return;
    await viewer.prepare(id,{
      dimensions:[meta.width,meta.height],spacing:[meta.spacing,meta.spacing],
      origin:[meta.x_min,meta.patient_y,meta.z_max],direction:[1,0,0,0,0,-1],frameOfReferenceUID:series.series_key,
    });
    if(pendingLocator!==job||$('coronalView').hidden||$('workstation').hidden)return;
    await viewer.display('coronal',[id],0,...imageWindow);
    if(pendingLocator!==job)return;
    state.locator={meta,url};drawCoronal();
  }catch(error){
    if(pendingLocator===job)throw error;
  }finally{
    if(pendingLocator===job)pendingLocator=null;
  }
}
const loadVisibleLocator=safely(loadLocator);
function loadImages(direction=0){
  if(!viewer||!state.series)return;
  void loadVisibleLocator();
  const {scope,imageIds}=imageStack(),index=state.index,url=imageIds[index];
  if(axialTask&&state.loading&&latestAxial?.url===url)return axialTask;
  const job={scope,imageIds,index,url,series:state.series,direction};
  latestAxial=job;
  if(state.image&&displayedAxial?.url===url){
    pendingAxial=null;setAxialLoading(false);draw();drawCoronal();
    return;
  }
  pendingAxial=job;
  setAxialLoading(true);
  if(!state.image)draw();
  axialTask??=drainAxial();
  return axialTask;
}
function transform(index=state.imageIndex??state.index){
  const origin=viewer.point('axial',toPatient(0,0,index));
  const step=viewer.point('axial',toPatient(1,1,index));
  return {sx:step[0]-origin[0],sy:step[1]-origin[1],ox:origin[0],oy:origin[1]};
}
function overlayCanvas(id){
  const canvas=$(id);
  if(!canvas.clientWidth||!canvas.clientHeight)return null;
  if(canvas.width!==canvas.clientWidth)canvas.width=canvas.clientWidth;
  if(canvas.height!==canvas.clientHeight)canvas.height=canvas.clientHeight;
  const ctx=canvas.getContext('2d');
  ctx.clearRect(0,0,canvas.width,canvas.height);
  return ctx;
}
function draw(){
  const ctx=overlayCanvas('axial');
  $('imageScale').hidden=true;
  if(!ctx||!state.image||state.imageSeries!==state.series?.series_key)return;
  const index=state.imageIndex;
  viewer.camera(state.zoom,state.pan);
  drawScale(index);
  const point=world=>viewer.point('axial',world);
  if($('overlays').checked){
    for(const finding of state.findings){
      const revision=finding.revision;
      if(revision.slice_key!==state.series.slice_keys[index])continue;
      if(revision.state==='excluded'&&finding.finding_id!==state.selected)continue;
      const preview=state.annotationPreview?.index===index?state.annotationPreview:null;
      const hidden=preview?.finding===finding.finding_id?preview.hide:null;
      if(hidden==='all')continue;
      const [x,y]=point(revision.center_lps);
      ctx.strokeStyle=finding.finding_id===state.selected?'#8ffff0':'#e3bd72';
      ctx.lineWidth=2;ctx.beginPath();ctx.arc(x,y,10,0,Math.PI*2);ctx.stroke();
      ctx.fillStyle=ctx.strokeStyle;ctx.fillText(finding.label,x+12,y);
      if(revision.contour&&hidden!=='contour')trace(ctx,revision.contour.points_lps.map(point),true);
      for(const axis of hidden==='axes'?[]:[revision.long_axis,revision.short_axis]){
        if(!axis)continue;
        const ends=axis.endpoints.map(point);
        trace(ctx,ends);
        if(finding.finding_id===state.selected&&state.draft?.status==='reviewing'&&!$('reviewPanel').hidden){
          for(const [x,y] of ends){ctx.beginPath();ctx.arc(x,y,3.5,0,Math.PI*2);ctx.stroke();}
        }
      }
    }
  }
  if(state.annotationPreview?.index===index){
    ctx.strokeStyle='#ffca78';ctx.lineWidth=2;
    for(const path of state.annotationPreview.paths)trace(ctx,path.points.map(point),path.closed);
  }
  ctx.fillStyle='#ffca78';
  for(const pixel of state.points){
    const [x,y]=point(toPatient(pixel[0],pixel[1],index));
    ctx.fillRect(x-3,y-3,6,6);
  }
}
function trace(ctx,points,closed=false){
  if(!points.length)return;
  ctx.beginPath();ctx.moveTo(...points[0]);
  for(const point of points.slice(1))ctx.lineTo(...point);
  if(closed)ctx.closePath();
  ctx.stroke();
}
function drawScale(index){
  const {sx}=transform(index),pxPerMm=Math.abs(sx)/state.series.geometry.spacing[1];
  if(!Number.isFinite(pxPerMm)||pxPerMm<=0)return;
  const limit=Math.min(120,$('axial').clientWidth/4);
  const length=[100,50,20,10,5,2,1].find(mm=>mm*pxPerMm<=limit);
  if(!length)return;
  const scale=$('imageScale');
  scale.style.setProperty('--scale-length',`${length*pxPerMm}px`);
  scale.textContent=`${length} mm`;
  scale.hidden=false;
}
function drawCoronal(){
  const ctx=overlayCanvas('coronal');
  const index=state.imageIndex;
  if(!ctx||index===null||!$('overlays').checked||state.locator?.url!==wantedLocatorUrl||!state.locator)return;
  const {meta}=state.locator,point=(x,z)=>viewer.point('coronal',[x,meta.patient_y,z]);
  const finding=state.findings.find(f=>f.finding_id===state.selected);
  const g=state.series.geometry;
  const pixel=finding?toPixel(finding.revision.center_lps,index):[g.columns/2,g.rows/2];
  const z=toPatient(pixel[0],pixel[1],index)[2];
  ctx.strokeStyle='#82f0dc';ctx.beginPath();
  ctx.moveTo(...point(meta.x_min,z));ctx.lineTo(...point(meta.x_min+meta.width*meta.spacing,z));
  if(finding){
    const x=finding.revision.center_lps[0];
    ctx.moveTo(...point(x,meta.z_max));ctx.lineTo(...point(x,meta.z_max-meta.height*meta.spacing));
  }
  ctx.stroke();
}
function toPatient(x,y,index=state.index){const g=state.series.geometry;return g.origins[index].map((v,i)=>v+g.row[i]*x*g.spacing[1]+g.column[i]*y*g.spacing[0]);}
function toPixel(p,index){const g=state.series.geometry,d=p.map((v,i)=>v-g.origins[index][i]);return [d.reduce((s,v,i)=>s+v*g.row[i],0)/g.spacing[1],d.reduce((s,v,i)=>s+v*g.column[i],0)/g.spacing[0]];}
async function slice(index){
  if(!state.series)return;
  const previous=state.index;
  state.index=Math.max(0,Math.min(state.series.slice_keys.length-1,index));
  if(state.index!==previous)state.cancelAnnotationPreview?.();
  $('slice').value=state.index;
  state.points=[];
  await loadImages(Math.sign(state.index-previous));
}
$('slice').oninput=safely(e=>slice(Number(e.target.value)));$('previousSlice').onclick=safely(()=>slice(state.index-1));$('nextSlice').onclick=safely(()=>slice(state.index+1));
for(const id of ['center','width'])$(id).onchange=safely(changeImageWindow);
function applyWindow(center,width){
  $('center').value=Math.round(center);$('width').value=Math.round(width);
  changeImageWindow();
}
$('lungWindow').onclick=safely(()=>applyWindow(-600,1500));
$('mediastinumWindow').onclick=safely(()=>applyWindow(40,400));
function updateZoomLabel(){
  $('zoomLabel').textContent=`${Math.round(state.zoom*100)}%`;
  $('zoomOut').disabled=state.zoom<=.25;
  $('zoomIn').disabled=state.zoom>=8;
}
$('resetView').onclick=()=>{
  state.zoom=1;state.pan=[0,0];
  updateZoomLabel();
  draw();
};
$('overlays').onchange=()=>{draw();drawCoronal();};
for(const [id,layout] of [['axialLayout','axial'],['coronalLayout','coronal']]){
  $(id).onclick=()=>{state.reviewLayout=layout;updateReviewLayout(true);};
}
const viewToolHints={
  window:'左键拖动调窗',
  pan:'左键拖动平移',
  zoom:'左键向上拖动放大，向下拖动缩小',
  probe:'移动指针查看当前像素的 HU 值',
};
function updateViewTool(annotationHint){
  for(const button of document.querySelectorAll('[data-view-tool]')){
    button.setAttribute('aria-pressed',String(!state.tool&&button.dataset.viewTool===state.viewTool));
  }
  $('axial').dataset.tool=state.tool?'annotate':state.viewTool;
  $('probeValue').hidden=true;
  $('toolHint').textContent=annotationHint
    ? `${annotationHint} · Esc 取消`
    : `${viewToolHints[state.viewTool]} · 滚轮翻层 · Ctrl+滚轮以指针为中心缩放 · 右键拖动平移`;
}
const axial=$('axial');
function viewCenter(){return [axial.clientWidth/2,axial.clientHeight/2];}
function canvasPoint(event){
  const rect=axial.getBoundingClientRect();
  return [event.clientX-rect.left,event.clientY-rect.top];
}
function positionAt(world,anchor){
  const [x,y]=viewer.point('axial',world);
  state.pan=[state.pan[0]+anchor[0]-x,state.pan[1]+anchor[1]-y];
  draw();
}
function centerFinding(world){
  if(state.image)positionAt(world,viewCenter());
}
function zoomAt(factor,anchor=viewCenter()){
  if(!state.image)return;
  const zoom=Math.max(.25,Math.min(8,state.zoom*factor));
  if(zoom===state.zoom)return;
  const world=viewer.world('axial',anchor);
  state.zoom=zoom;
  viewer.camera(zoom,state.pan);
  positionAt(world,anchor);
  updateZoomLabel();
}
$('zoomIn').onclick=()=>zoomAt(1.25);
$('zoomOut').onclick=()=>zoomAt(.8);
axial.onwheel=safely(async e=>{
  if(!e.deltaY)return;
  e.preventDefault();
  if(e.ctrlKey)zoomAt(Math.pow(1.15,-Math.sign(e.deltaY)),canvasPoint(e));
  else await slice(state.index+Math.sign(e.deltaY));
});
function probeAt(point){
  const g=state.series.geometry;
  const [x,y]=toPixel(viewer.world('axial',point),state.imageIndex).map(Math.round);
  const label=$('probeValue');
  label.hidden=x<0||y<0||x>=g.columns||y>=g.rows;
  if(!label.hidden)label.textContent=`${Math.round(state.image.getPixelData()[y*g.columns+x])} HU`;
}
axial.oncontextmenu=e=>e.preventDefault();
let drag=null;
axial.onpointerdown=e=>{
  if(!state.image||drag)return;
  const mode=e.button===2||e.button===1?'pan':e.button===0&&!state.tool?state.viewTool:null;
  if(!mode||mode==='probe')return;
  const point=canvasPoint(e);
  drag={mode,id:e.pointerId,point,start:point,window:[...imageWindow]};
  axial.setPointerCapture(e.pointerId);
  axial.classList.add('dragging');
  e.preventDefault();
};
axial.onpointermove=e=>{
  if(!state.image)return;
  const point=canvasPoint(e);
  if(!drag){
    if(!state.tool&&state.viewTool==='probe')probeAt(point);
    return;
  }
  if(drag.id!==e.pointerId)return;
  const dx=point[0]-drag.point[0],dy=point[1]-drag.point[1];
  if(drag.mode==='pan'){
    state.pan=[state.pan[0]+dx,state.pan[1]+dy];draw();
  }else if(drag.mode==='zoom'){
    zoomAt(Math.exp(-dy/180),drag.start);
  }else{
    const [center,width]=drag.window,sensitivity=Math.max(1,width/300);
    applyWindow(center+(point[1]-drag.start[1])*sensitivity,Math.max(1,width+(point[0]-drag.start[0])*sensitivity));
  }
  drag.point=point;
};
function endDrag(e){
  if(drag?.id!==e.pointerId)return;
  drag=null;
  axial.classList.remove('dragging');
}
axial.onpointerup=axial.onpointercancel=axial.onlostpointercapture=endDrag;
axial.onpointerleave=()=>{$('probeValue').hidden=true;};
const resizeImages=new ResizeObserver(()=>{viewer?.resize();draw();drawCoronal();});
resizeImages.observe($('axial'));
resizeImages.observe($('coronal'));
export {$,state,api,act,safely,message,el,refresh,loadImages,draw,drawCoronal,transform,toPatient,toPixel,slice,openSeries,projects,updateWorkflow,setWorkflowStep,updateViewTool,centerFinding};
