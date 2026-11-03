import {$,state,act,safely,message,el,refresh} from './app.js';
import {updateDraft} from './review-ui.js';
let pollTimer;
const controls=el('div',undefined,'toolbar'),runs=el('select'),use=el('button','从此运行建立复核分支'),threshold=el('input');
runs.id='runChoice';threshold.id='threshold';threshold.type='number';threshold.min=0;threshold.max=1;threshold.step=.01;threshold.value=.02;threshold.title='候选分数阈值，不代表恶性概率';
controls.append(el('label','阈值'),threshold,runs,use);$('runStatus').after(controls);
async function syncRuns(){if(!state.series)return;await refresh();const list=state.data.runs.filter(r=>r.series_key===state.series.series_key);const previous=runs.value;runs.replaceChildren(...list.map(r=>new Option(`${r.run_id.slice(-6)} · ${{queued:'排队',running:'运行中',failed:'失败',succeeded:'成功'}[r.state]}`,r.run_id)));if(list.some(r=>r.run_id===previous))runs.value=previous;else if(list.length)runs.value=list.at(-1).run_id;const last=list.at(-1);$('runStatus').textContent=last?`${last.message} · 候选 ${last.candidate_count??'未定义'} · ${last.model?.version??'无模型版本'}`:'未配置检测模型，可继续人工标注';const chosen=list.find(r=>r.run_id===runs.value);use.disabled=!chosen||chosen.state!=='succeeded';$('startRun').disabled=list.some(r=>['queued','running'].includes(r.state));clearTimeout(pollTimer);if(list.some(r=>['queued','running'].includes(r.state)))pollTimer=setTimeout(safely(syncRuns),500);}
state.afterSeries.push(syncRuns);runs.onchange=safely(syncRuns);
$('startRun').onclick=safely(async()=>{await act('startRun',{project:state.project,series:state.series.series_key,request_key:crypto.randomUUID(),threshold:Number(threshold.value)});await syncRuns();message('任务已登记；现有复核草稿保持原运行');});
use.onclick=safely(async()=>{state.draft=await act('startDraft',{project:state.project,series:state.series.series_key,operator:state.data.project.operator,run_id:runs.value});state.selected=null;await updateDraft();message('已打开所选运行的独立复核分支');});
