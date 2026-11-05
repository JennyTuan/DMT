import {$,state,act,safely,message,el,refresh,updateWorkflow} from './app.js';
import {updateDraft} from './review-ui.js';

let pollTimer,starting=false;
const modelChoice=$('analysisModel'),start=$('startRun');
const profileLabels={standard:'标准', 'low-memory':'低显存'};
const modelLabel=model=>[model.label,model.version,profileLabels[model.profile]??model.profile].filter(Boolean).join(' · ');
modelChoice.replaceChildren(...state.analysisModels.map(model=>new Option(modelLabel(model),model.id)));
if(!state.modelConfigured)modelChoice.add(new Option('未配置检测模型',''));

const advanced=el('details',undefined,'analysisAdvanced');
advanced.hidden=!state.modelConfigured;
const threshold=el('input');
threshold.id='threshold';threshold.type='number';threshold.min=0;threshold.max=1;
threshold.step=.01;threshold.value=.02;
threshold.setAttribute('aria-describedby','thresholdHelp');
const thresholdLabel=el('label','候选最低分数');
thresholdLabel.append(threshold);
const thresholdHelp=el('p','只保留达到这个分数的 AI 候选。调高通常会减少候选，也可能漏掉结节。分数仅用于候选筛选，日常测试用默认值 0.02 即可。','thresholdHelp');
thresholdHelp.id='thresholdHelp';
advanced.append(el('summary','高级设置'),thresholdLabel,thresholdHelp);
const use=el('button','复核本次分析结果');
use.id='useRun';use.type='button';use.hidden=true;
$('analysisPanel').querySelector('.analysisActions').append(use);
$('analysisPanel').append(advanced);

function configuredModel(run){
  return state.analysisModels.find(model=>run.model_id ? model.id===run.model_id
    : model.name===run.model?.name && model.version===run.model?.version && model.profile===run.model?.execution_profile);
}
function runModelLabel(run){
  const model=configuredModel(run);
  if(model)return modelLabel(model);
  return [run.model?.name,run.model?.version].filter(Boolean).join(' · ')||run.model_id||'模型未记录';
}
function updateAnalysisControls(){
  const unavailable=!state.modelConfigured||starting||state.runBusy;
  modelChoice.disabled=unavailable;
  threshold.disabled=unavailable;
  start.disabled=unavailable;
  const run=state.analysisRun;
  start.textContent=run?(configuredModel(run)?.id===modelChoice.value?'重新分析':'用所选模型分析'):'开始 AI 分析';
}
async function syncRuns(){
  if(!state.series)return;
  await refresh();
  const list=state.data.runs.filter(r=>r.series_key===state.series.series_key);
  const latest=list.at(-1);
  state.analysisRun=latest;
  const status=$('runStatus');
  status.dataset.state=latest?.state??'';
  status.hidden=!latest&&state.modelConfigured;
  status.textContent=latest
    ? [latest.message,latest.candidate_count==null?'':`${latest.candidate_count} 个候选`,runModelLabel(latest)].filter(Boolean).join(' · ')
    : state.modelConfigured?'':'未配置检测模型，可继续人工复核';
  state.runBusy=list.some(run=>['queued','running'].includes(run.state));
  state.runReady=latest?.state==='succeeded';
  state.runFailed=latest?.state==='failed';
  updateAnalysisControls();
  updateWorkflow();
  clearTimeout(pollTimer);
  if(state.runBusy)pollTimer=setTimeout(safely(syncRuns),500);
}
state.afterSeries.push(syncRuns);
modelChoice.onchange=updateAnalysisControls;
start.onclick=safely(async()=>{
  if(starting||state.runBusy||!modelChoice.value)return;
  const value=Number(threshold.value);
  if(!threshold.value||!threshold.checkValidity()){
    advanced.open=true;
    threshold.reportValidity();
    return;
  }
  starting=true;
  updateAnalysisControls();
  try{
    await act('startRun',{project:state.project,series:state.series.series_key,request_key:crypto.randomUUID(),threshold:value,model_id:modelChoice.value});
    await syncRuns();
    message('AI 分析任务已登记');
  }finally{
    starting=false;
    updateAnalysisControls();
  }
});
use.onclick=safely(async()=>{
  if(!state.runReady)return;
  state.draft=await act('startDraft',{project:state.project,series:state.series.series_key,operator:state.data.project.operator,run_id:state.analysisRun.run_id});
  state.selected=null;
  await updateDraft();
  message('已打开本次分析的复核草稿');
});
