import {$,state,act,safely,message,el,refresh,loadImages,draw,drawCoronal,transform,toPatient,toPixel,slice,setWorkflowStep,updateViewTool,centerFinding} from './app.js';
import {perpendicularAxis} from './review-geometry.js';
const states={pending:'待复核',confirmed:'已确认',excluded:'已排除',uncertain:'存疑'};
const types={unknown:'未判定',solid:'实性',part_solid:'部分实性',ground_glass:'纯磨玻璃'};
const locations={unknown:'未判定',right:'右肺 · 肺叶未定',RUL:'右上叶',RML:'右中叶',RLL:'右下叶',left:'左肺 · 肺叶未定',LUL:'左上叶',LLL:'左下叶'};
const reasons={'':'请选择原因',false_positive:'非结节候选',duplicate:'重复',artifact:'伪影',insufficient_evidence:'证据不足',withdrawn:'撤回',correction:'修正',not_measured:'未测量',not_visible:'不可见',unreliable_boundary:'边界不可靠',location_changed:'位置已修改'};
const selected=()=>state.findings.find(f=>f.finding_id===state.selected);
const operator=()=>state.data.project.operator;
let writing=false,lastEdit=null,gesture=null,pairPoints=[],detailsFor=null;
async function updateDraft(){
  if(!state.draft)return;
  const project=state.project,draft=state.draft.draft_id;
  const updated=await act('getDraft',{project,draft});
  if(state.project!==project||state.draft?.draft_id!==draft)return;
  state.draft=updated;state.findings=updated.findings;
  if(!$('workstation').hidden)setWorkflowStep(3);
  render();draw();drawCoronal();
}
function editable(){return state.draft&&state.draft.series_key===state.series?.series_key&&state.draft.status!=='completed';}
async function selectFinding(fid,{center=false}={}){
  if(state.selected!==fid)detailsFor=null;
  state.selected=fid;
  setTool();render();
  const finding=selected(),index=state.series.slice_keys.indexOf(finding.revision.slice_key);
  await slice(index);
  if(state.selected===fid&&state.imageIndex===index&&(center||state.zoom>1))centerFinding(finding.revision.center_lps);
}
function editContext(f){
  return {project:state.project,draft:state.draft.draft_id,operator:operator(),
    ...(f?{finding:f.finding_id,expected_revision_id:f.revision.revision_id}:{})};
}
const currentDraft=context=>context.project===state.project&&context.draft===state.draft?.draft_id;
async function writeReview(action,context,values,{remember=false,select=false}={}){
  if(writing)throw Error('正在保存，请稍候');
  if(!editable()||!currentDraft(context)||$('reviewPanel').hidden||$('workstation').hidden)throw Error('请先打开可编辑的复核草稿');
  const selectedBefore=state.selected;
  writing=true;
  try{
    const result=await act(action,{...context,...values});
    if(currentDraft(context)){
      if(remember)lastEdit={...context,finding:result.finding_id,expected_revision_id:result.revision.revision_id};
      else lastEdit=null;
      if(select&&state.selected===selectedBefore)state.selected=result.finding_id;
      await updateDraft();message('修订已保存 · '+new Date().toLocaleTimeString());
    }
    return result;
  }finally{writing=false;}
}
async function patch(values,f=selected()){
  if(!f||!editable())throw Error('请先选择可编辑观察');
  return writeReview('reviseFinding',editContext(f),{patch:values},{remember:true});
}
async function undo(f){
  const context=editContext(f);
  await writeReview('undoFinding',context,{}, {select:true});
  if(currentDraft(context))await selectFinding(f.finding_id);
}
async function decide(f,values){
  const rows=state.findings;
  const i=rows.findIndex(row=>row.finding_id===f.finding_id);
  const next=[...rows.slice(i+1),...rows.slice(0,i)].find(row=>row.revision.state==='pending');
  setTool();
  await patch(values,f);
  if(next&&visibleFindings().some(row=>row.finding_id===next.finding_id)&&state.selected===f.finding_id&&state.findings.some(row=>row.finding_id===next.finding_id&&row.revision.state==='pending')){
    await selectFinding(next.finding_id);
  }
}
function selectInput(label,id,values,current){const wrap=el('label',label);const input=el('select');input.id=id;input.setAttribute('aria-label',label);for(const [key,value] of Object.entries(values))input.add(new Option(value,key));input.value=current??'';input.disabled=!editable();wrap.append(input);return wrap;}
function button(label,handler,disabled=false){const b=el('button',label);b.type='button';b.onclick=safely(handler);b.disabled=disabled;return b;}
function visibleFindings(){
  const filter=$('findingFilter').value;
  return state.findings.filter(f=>!filter||f.revision.state===filter);
}
function adjacentFinding(rows,direction){
  const index=rows.findIndex(f=>f.finding_id===state.selected);
  return rows[index<0?0:index+direction];
}
async function moveSelection(direction){
  const finding=adjacentFinding(visibleFindings(),direction);
  if(finding)await selectFinding(finding.finding_id);
}
function renderFindingList(){
  const list=$('findings');
  const focused=list.contains(document.activeElement);
  const rows=visibleFindings();
  list.replaceChildren();
  $('findingFilter').disabled=!state.findings.length;
  $('previousFinding').disabled=!adjacentFinding(rows,-1);
  $('nextFinding').disabled=!adjacentFinding(rows,1);
  if(!rows.length){
    list.append(el('p',state.findings.length?'没有符合筛选条件的结节':'尚无观察记录','findingEmpty'));
    return;
  }
  const header=el('div',undefined,'findingGrid findingHeader');
  header.append(el('span','编号'),el('span','状态'),el('span','长径（mm）','findingLength'));
  list.append(header);
  let activeRow=null;
  for(const f of rows){
    const row=button(undefined,()=>selectFinding(f.finding_id));
    const active=f.finding_id===state.selected;
    row.className='finding findingGrid'+(active?' selected':'');
    row.setAttribute('aria-pressed',String(active));
    row.dataset.revision=f.revision.revision_id;
    const status=el('span',states[f.revision.state],'findingState');
    status.dataset.state=f.revision.state;
    const length=f.revision.long_axis?.length_mm.toFixed(1);
    row.setAttribute('aria-label',`${f.label}，${status.textContent}，${length===undefined?'长径未测量':`长径 ${length} 毫米`}`);
    row.append(el('span',f.label),status,el('span',length??'—','findingLength'));
    list.append(row);
    if(active)activeRow=row;
  }
  if(activeRow){
    if(focused)activeRow.focus({preventScroll:true});
    const row=activeRow.getBoundingClientRect(),bounds=list.getBoundingClientRect();
    const top=bounds.top+header.offsetHeight;
    if(row.top<top)list.scrollTop+=row.top-top;
    else if(row.bottom>bounds.bottom)list.scrollTop+=row.bottom-bounds.bottom;
  }
}
function confirmation(id,text){
  const label=el('label',undefined,'check'),input=el('input');
  input.type='checkbox';input.id=id;input.required=true;
  label.append(input,document.createTextNode(text));
  return label;
}
function renderCompletion(){
  const panel=$('completion');
  panel.replaceChildren();
  if(!state.draft||editable())return;
  panel.append(el('p','已完成 · 快照已冻结','saved'),button('重新编辑（新版本）',async()=>{
    state.draft=await act('reopenCase',{project:state.project,snapshot:state.draft.snapshot_id,operator:operator()});
    await updateDraft();message('新草稿已建立，旧快照保持不变');
  }));
}
const completionDialog=$('completeReviewDialog');
state.openCompletion=()=>{
  if(!editable()||state.draft.counts.pending)return;
  if(writing||gesture||pairPoints.length)throw Error('请先保存或取消当前标注');
  const c=state.draft.counts,checks=$('completeReviewChecks');
  $('completeReviewSummary').textContent=`${c.confirmed} 项确认 · ${c.excluded} 项排除 · ${c.uncertain} 项存疑`;
  $('completeReviewError').hidden=true;
  checks.replaceChildren(confirmation('browsed','我已浏览整例原始影像'));
  if(!c.confirmed)checks.append(confirmation('confirmZero','确认本例以零确认结节结案'));
  completionDialog.showModal();
};
$('cancelReviewCompletion').onclick=()=>completionDialog.close();
completionDialog.oncancel=event=>{if(writing)event.preventDefault();};
$('completeReviewForm').onsubmit=async event=>{
  event.preventDefault();
  if(writing)return;
  writing=true;
  $('commitReviewCompletion').disabled=true;$('cancelReviewCompletion').disabled=true;
  const error=$('completeReviewError');
  error.hidden=true;
  try{
    const snapshot=await act('completeCase',{
      project:state.project,draft:state.draft.draft_id,expected_version:state.draft.version,
      operator:operator(),browsed:$('browsed').checked,confirm_zero:$('confirmZero')?.checked??false
    });
    completionDialog.close();
    await updateDraft();await refresh();message('已冻结快照 '+snapshot.snapshot_id);
  }catch(e){
    if(completionDialog.open){error.textContent=e.message;error.hidden=false;}
    else message(e.message,true);
  }finally{
    writing=false;
    $('commitReviewCompletion').disabled=false;$('cancelReviewCompletion').disabled=false;
  }
};
function renderDecision(panel,f){
  const r=f.revision,actions=el('div',undefined,'toolbar decisionActions');
  const options=el('div',undefined,'decisionOptions');
  options.id='decisionOptions';options.hidden=true;
  function choose(kind,heading,choices,apply){
    if(!options.hidden&&options.dataset.kind===kind){
      options.hidden=true;
      confirm.setAttribute('aria-expanded','false');exclude.setAttribute('aria-expanded','false');
      return;
    }
    options.dataset.kind=kind;
    const row=el('div',undefined,'decisionChoices');
    for(const [label,value] of choices)row.append(button(label,()=>apply(value)));
    options.replaceChildren(el('p',heading),row);
    options.hidden=false;
    confirm.setAttribute('aria-expanded',String(kind==='missing'));
    exclude.setAttribute('aria-expanded',String(kind==='exclude'));
    row.querySelector('button')?.focus();
  }
  const needsReason=!r.long_axis||!r.short_axis;
  const confirm=button('确认',()=>{
    if(needsReason&&r.state!=='confirmed'){
      choose('missing','无法完成双径测量时，选择原因后确认',
        [['未测量','not_measured'],['不可见','not_visible'],['边界不可靠','unreliable_boundary']],
        missing_reason=>decide(f,{state:'confirmed',reason:null,missing_reason}));
      return;
    }
    return decide(f,{state:'confirmed',reason:null});
  },r.state==='confirmed');
  confirm.classList.add('primary');
  const exclusionReasons=[['非结节','false_positive'],['重复','duplicate'],['伪影','artifact']];
  if(f.original.source==='manual')exclusionReasons.push(['误标','withdrawn']);
  const exclude=button('排除',()=>choose('exclude','选择排除原因',exclusionReasons,
    reason=>decide(f,{state:'excluded',reason})));
  const uncertain=button('存疑',()=>decide(f,{state:'uncertain',reason:'insufficient_evidence'}),r.state==='uncertain'&&r.reason==='insufficient_evidence');
  uncertain.title='标为存疑（证据不足）';
  for(const control of [confirm,exclude]){control.setAttribute('aria-controls',options.id);control.setAttribute('aria-expanded','false');}
  actions.append(confirm,exclude,uncertain);panel.append(actions,options);
}
function renderDetails(f){
  const r=f.revision,details=el('details',undefined,'reviewMore');
  details.append(el('summary','观察详情'));
  details.open=detailsFor===f.finding_id;
  details.ontoggle=()=>{if(state.selected===f.finding_id)detailsFor=details.open?f.finding_id:null;};
  const location=r.lobe==='unknown'?r.side:r.lobe;
  if(editable()){
    const fields=el('div',undefined,'twoCols');
    const position=selectInput('肺部位置','noduleLocation',locations,location);
    const type=selectInput('结节类型','noduleType',types,r.nodule_type);
    const positionInput=position.querySelector('select'),typeInput=type.querySelector('select');
    positionInput.onchange=safely(async()=>{
      const value=positionInput.value;
      const side=value.startsWith('L')?'left':value.startsWith('R')?'right':['left','right'].includes(value)?value:'unknown';
      try{await patch({side,lobe:value===side?'unknown':value},f);}
      catch(error){positionInput.value=location;throw error;}
    });
    typeInput.onchange=safely(async()=>{
      try{await patch({nodule_type:typeInput.value},f);}
      catch(error){typeInput.value=r.nodule_type;throw error;}
    });
    fields.append(position,type);details.append(fields);
    details.append(button('修改定位',()=>setTool('move')));
  }else{
    details.append(el('p',`肺部位置 ${locations[location]} · 结节类型 ${types[r.nodule_type]}`));
  }
  if(r.missing_reason)details.append(el('p',`缺测原因 · ${reasons[r.missing_reason]??r.missing_reason}`));
  const history=el('details',undefined,'findingHistory');
  history.append(el('summary','来源与修订记录'));
  history.append(el('p',`原始来源 ${f.original.source==='ai'?'AI':'人工'} · 检测分数 ${f.original.score??'不适用'}`));
  const records=el('pre');
  history.append(records);
  history.ontoggle=safely(async()=>{
    if(!history.open)return;
    const rows=await act('findingHistory',{project:state.project,draft:state.draft.draft_id,finding:f.finding_id});
    records.textContent=rows.map(r=>`${r.at} · ${r.operator} · ${r.action} · ${states[r.state]} · ${reasons[r.reason]??'—'}\n长/短径 ${r.long_axis?.length_mm.toFixed(1)??'—'} / ${r.short_axis?.length_mm.toFixed(1)??'—'}`).join('\n');
  });
  details.append(history);
  return details;
}
function render(){
  $('count').textContent=state.draft?`${state.findings.length} 项 · 待复核 ${state.draft.counts.pending}`:'0 项';
  renderFindingList();
  const f=selected(),editor=$('findingEditor');
  editor.replaceChildren();
  $('returnFinding').disabled=!f;
  $('undoReview').disabled=!editable()||!lastEdit||!currentDraft(lastEdit)||
    !state.findings.some(item=>item.finding_id===lastEdit.finding&&item.revision.revision_id===lastEdit.expected_revision_id);
  $('undoReview').hidden=$('undoReview').disabled;
  for(const id of ['addFinding','addPair'])$(id).disabled=!editable();
  if(f){
    const r=f.revision,heading=el('div',undefined,'sectionTitle');
    const status=el('span',states[r.state],'findingState');
    status.dataset.state=r.state;
    heading.append(el('h2',f.label+' · '+(f.original.source==='manual'?'人工新增':'AI 候选')),status);
    const measurement=el('div',undefined,'reviewMeasurement');
    const text=r.long_axis||r.short_axis?`长径 ${r.long_axis?.length_mm.toFixed(1)??'—'} mm / 短径 ${r.short_axis?.length_mm.toFixed(1)??'—'} mm`:'未测量';
    measurement.append(el('span',text,'measurements'));
    if(editable())measurement.append(button(r.long_axis?'重测双径':'测量双径',()=>startOnFinding('redraw_pair')));
    editor.append(heading,measurement);
    const location=r.lobe==='unknown'?r.side:r.lobe;
    const facts=[location==='unknown'?'位置未判定':locations[location]];
    if(r.reason)facts.push(reasons[r.reason]??r.reason);
    if(r.contour)facts.push('已保存单层轮廓');
    editor.append(el('p',facts.join(' · '),'contourStatus'));
    if(editable())renderDecision(editor,f);
    editor.append(renderDetails(f));
  }else if(state.findings.length){
    editor.append(el('p','选择一项观察，查看原片和测量。','findingEmpty'));
  }
  renderCompletion();
}
const toolButtons={add:'addFinding',add_pair:'addPair'};
const toolInstructions={
  add:'点击原片添加观察',
  move:'点击新位置，原有径线将清空',
  add_pair:'依次点击长径两端、短径两端，完成后新增观察',
  redraw_pair:'依次点击长径两端、短径两端，完成后替换双径',
};
const pairTools=new Set(['add_pair','redraw_pair']);
const axial=$('axial');
function preview(paths=[],hide=null){
  state.annotationPreview={index:state.index,finding:state.selected,hide,paths};
  draw();
}
function setTool(tool=null){
  const pointer=gesture?.id;
  gesture=null;pairPoints=[];state.annotationPreview=null;
  if(pointer!==undefined&&axial.hasPointerCapture(pointer))axial.releasePointerCapture(pointer);
  state.tool=tool;state.points=[];
  for(const [name,id] of Object.entries(toolButtons))$(id).setAttribute('aria-pressed',String(name===tool));
  updateViewTool(toolInstructions[tool]);
  if(tool==='redraw_pair')preview([],'all');
  else draw();
}
state.cancelAnnotationPreview=()=>{
  if(gesture||pairTools.has(state.tool))setTool();
};
async function startOnFinding(tool){
  const f=selected();
  if(!f||!editable())return;
  const index=state.series.slice_keys.indexOf(f.revision.slice_key);
  if(state.index!==index||state.imageIndex!==index)await slice(index);
  if(state.selected===f.finding_id&&state.index===index&&state.imageIndex===index)setTool(tool);
}
function markable(){
  return !writing&&editable()&&!$('reviewPanel').hidden&&!$('workstation').hidden&&
    !state.loading&&state.image&&state.imageIndex===state.index&&state.imageSeries===state.series.series_key;
}
function eventPoint(e){
  const rect=axial.getBoundingClientRect(),t=transform(),g=state.series.geometry;
  const canvas=[e.clientX-rect.left,e.clientY-rect.top];
  const x=(canvas[0]-t.ox)/t.sx,y=(canvas[1]-t.oy)/t.sy;
  if(x<0||x>g.columns-1||y<0||y>g.rows-1)return null;
  return {canvas,pixel:[x,y],world:toPatient(x,y)};
}
function project(point){
  const [x,y]=toPixel(point,state.index),t=transform();
  return [t.ox+x*t.sx,t.oy+y*t.sy];
}
const path=points=>({points});
function average(points){
  return points[0].map((_,i)=>points.reduce((sum,p)=>sum+p[i],0)/points.length);
}
async function addGeometry(point,geometry){
  await writeReview('addFinding',editContext(),{point,...(geometry?{geometry}:{})},{select:true});
  await loadImages();
}
const reviewGeometry=values=>({...values,state:'pending',reason:null});
async function clickAnnotation(e){
  const tool=state.tool;
  if(!tool||!editable()||writing)return;
  if(!markable())throw Error('影像正在加载，请稍候再标注');
  const point=eventPoint(e);
  if(!point)return;
  if(tool==='add'){
    setTool();
    await addGeometry(point.world);
    return;
  }
  if(tool==='move'){
    setTool();
    await patch(reviewGeometry({center_lps:point.world,slice_key:state.series.slice_keys[state.index]}));
    await loadImages();
    return;
  }
  const f=selected(),newPair=tool==='add_pair';
  if(!newPair&&f?.revision.slice_key!==state.series.slice_keys[state.index])throw Error('请先返回该结节层面，或使用修改位置');
  pairPoints.push(point.world);
  const long=pairPoints.slice(0,2);
  if(pairPoints.length<4){
    preview([path(long),path(pairPoints.slice(2))],tool==='redraw_pair'?'all':null);
    return;
  }
  const short=perpendicularAxis(long,pairPoints.slice(2),state.series.geometry.normal);
  setTool();
  const axes={long_axis:long,short_axis:short};
  if(newPair)await addGeometry(average(long),axes);
  else await patch(reviewGeometry(axes),f);
}
function axisHandle(f,canvas){
  if(!f||state.viewTool!=='window'||!$('overlays').checked||f.revision.slice_key!==state.series.slice_keys[state.index])return null;
  let best=null;
  for(const name of ['long_axis','short_axis']){
    for(const [i,point] of (f.revision[name]?.endpoints||[]).entries()){
      const [x,y]=project(point),distance=Math.hypot(x-canvas[0],y-canvas[1]);
      if(distance<=8&&(!best||distance<best.distance))best={name,i,distance};
    }
  }
  return best;
}
function revisedAxes(g,point){
  const r=g.finding.revision,normal=state.series.geometry.normal;
  const ends=r[g.handle.name].endpoints.map((p,i)=>i===g.handle.i?point:p);
  if(g.handle.name==='short_axis'){
    const ordered=g.handle.i===0?[ends[1],ends[0]]:ends;
    const projected=perpendicularAxis(r.long_axis.endpoints,ordered,normal);
    return {short_axis:g.handle.i===0?projected.reverse():projected};
  }
  const result={long_axis:ends};
  if(r.short_axis)result.short_axis=perpendicularAxis(ends,r.short_axis.endpoints,normal,{centered:true});
  return result;
}
function startGesture(e){
  if(e.button!==0||state.tool||!markable())return;
  const point=eventPoint(e),finding=selected();
  const handle=point&&axisHandle(finding,point.canvas);
  if(!handle)return;
  e.preventDefault();e.stopImmediatePropagation();
  gesture={id:e.pointerId,index:state.index,finding,handle,context:editContext(finding),start:point.canvas};
  axial.setPointerCapture(e.pointerId);
}
function gestureCurrent(g){
  return markable()&&g.index===state.index&&currentDraft(g.context)&&
    selected()?.revision.revision_id===g.context.expected_revision_id;
}
function moveGesture(e){
  const g=gesture;
  if(!g||g.id!==e.pointerId||!gestureCurrent(g))return;
  const point=eventPoint(e);
  if(!point)return;
  const axes=revisedAxes(g,point.world),r=g.finding.revision;
  preview(['long_axis','short_axis'].map(name=>axes[name]||r[name]?.endpoints).filter(Boolean).map(points=>path(points)),'axes');
}
async function endGesture(e){
  const g=gesture;
  if(!g||g.id!==e.pointerId)return;
  const point=gestureCurrent(g)&&eventPoint(e);
  setTool();
  if(!point||Math.hypot(point.canvas[0]-g.start[0],point.canvas[1]-g.start[1])<2)return;
  await writeReview('reviseFinding',g.context,{patch:reviewGeometry(revisedAxes(g,point.world))},{remember:true});
}
state.afterSeries.push(async()=>{setTool();lastEdit=null;detailsFor=null;$('resetView').click();await refresh();const drafts=state.data.drafts.filter(d=>d.series_key===state.series.series_key);state.draft=drafts.at(-1)||null;$('manualDraft').disabled=false;if(state.draft)await updateDraft();else render();});
$('manualDraft').onclick=safely(async()=>{state.draft=await act('startDraft',{project:state.project,series:state.series.series_key,operator:operator()});state.selected=null;await updateDraft();message('人工复核草稿已保存');});
$('findingFilter').onchange=render;
$('previousFinding').onclick=safely(()=>moveSelection(-1));
$('nextFinding').onclick=safely(()=>moveSelection(1));
$('undoReview').onclick=safely(async()=>{
  const f=state.findings.find(item=>item.finding_id===lastEdit?.finding&&item.revision.revision_id===lastEdit.expected_revision_id);
  if(f&&currentDraft(lastEdit)){setTool();await undo(f);}
});
for(const button of document.querySelectorAll('[data-view-tool]')){
  button.onclick=()=>{state.viewTool=button.dataset.viewTool;setTool();};
}
for(const [tool,id] of Object.entries(toolButtons))$(id).onclick=()=>setTool(state.tool===tool?null:tool);
$('returnFinding').onclick=safely(async()=>{if(selected())await selectFinding(state.selected,{center:true});});
axial.addEventListener('click',safely(clickAnnotation));
axial.addEventListener('pointerdown',startGesture,true);
axial.addEventListener('pointermove',moveGesture);
axial.addEventListener('pointerup',safely(endGesture));
axial.addEventListener('pointercancel',()=>{if(gesture)setTool();});
axial.addEventListener('lostpointercapture',()=>{if(gesture)setTool();});
window.addEventListener('keydown',safely(async e=>{
  if(e.key==='Escape'&&(state.tool||gesture)&&!$('workstation').hidden&&!e.defaultPrevented){e.preventDefault();setTool();return;}
  if(completionDialog.open||['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName)||document.activeElement?.isContentEditable||!['ArrowUp','ArrowDown'].includes(e.key)||$('workstation').hidden||$('reviewPanel').hidden||!visibleFindings().length)return;
  e.preventDefault();await moveSelection(e.key==='ArrowDown'?1:-1);
}));
export {updateDraft,selectFinding};
