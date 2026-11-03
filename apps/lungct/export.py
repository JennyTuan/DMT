"""Whitelist-only, snapshot-based research packages with atomic publication."""
from copy import deepcopy
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
from . import NOTICE, VERSION
from .core import uid, now, owned, digest, encoded
from .viewer import locate

STUDY_FIELDS=['project_id','case_code','subject_key','study_key','series_key','snapshot_id','analysis_mode','run_id','run_state','ai_candidate_count','manual_count','confirmed_count','excluded_count','uncertain_count','research_source','synthetic','notice']
NODULE_FIELDS=['project_id','case_code','study_key','series_key','snapshot_id','finding_id','label','slice_key','center_lps_x','center_lps_y','center_lps_z','source','side','lobe','nodule_type','long_mm','short_mm','missing_reason','revision_id','notice']
ORIGINAL_FIELDS=['finding_id','series_key','run_id','source','center_lps','slice_key','box_lps','score']
REVISION_FIELDS=['revision_id','finding_id','previous_revision_id','operator','at','action','state','reason','center_lps','slice_key','side','lobe','nodule_type','missing_reason']
RUN_FIELDS=['run_id','series_key','state','complete','input_sha256','error_code','candidate_count','threshold','elapsed_seconds','model_to_lps']
LABELS=dict(project_id='研究项目键',case_code='研究病例号',subject_key='项目内受试者键',study_key='检查键',series_key='序列键',snapshot_id='冻结快照键',analysis_mode='分析方式',run_id='运行键',run_state='运行状态',ai_candidate_count='完整成功运行的原始候选数',manual_count='人工新增数',confirmed_count='已确认数',excluded_count='已排除数',uncertain_count='存疑数',research_source='研究来源',synthetic='是否合成样本',notice='科研声明',finding_id='单次观察稳定键',label='病例内显示编号',slice_key='原始切片键',center_lps_x='患者LPS中心X',center_lps_y='患者LPS中心Y',center_lps_z='患者LPS中心Z',source='原始来源',side='人工侧别',lobe='人工肺叶',nodule_type='人工结节类型',long_mm='人工长径',short_mm='人工短径',missing_reason='结构化缺测原因',revision_id='采用的修订键')
ENUMS={'analysis_mode':'manual=人工;ai=AI候选后人工复核','run_state':'not_run=未运行;queued=排队;running=运行中;succeeded=成功;failed=失败','source':'ai=AI;manual=人工','side':'left=左;right=右;unknown=未判定','lobe':'RUL=右上;RML=右中;RLL=右下;LUL=左上;LLL=左下;unknown=未判定','nodule_type':'solid=实性;part_solid=部分实性;ground_glass=纯磨玻璃;unknown=未判定','research_source':'screening=筛查;non_screening=非筛查;unknown=未知','synthetic':'true=合成;false=已登记数据','missing_reason':'not_measured=未测;not_visible=不可见;unreliable_boundary=边界不可靠;location_changed=位置变更'}


def whitelist(item,keys):return {k:deepcopy(item.get(k)) for k in keys}


def revision(value):
    result=whitelist(value,REVISION_FIELDS)
    for axis in ('long_axis','short_axis'):
        result[axis]=whitelist(value[axis],['endpoints','length_mm','slice_key','method']) if value.get(axis) else None
    return result


def run_export(run):
    if not run:return None
    result=whitelist(run,RUN_FIELDS)
    result['model']=whitelist(run['model'],['name','version','weight_sha256','preprocessing_sha256','license']) if run.get('model') else None
    return result


def write_csv(path,fields,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='raise');writer.writeheader();writer.writerows(rows)


class ExportService:
    def export_preview(self,project,study_keys=None):
        state=self.repo.read();owned(state,'projects',project,project)
        selected=study_keys if study_keys is not None else [s['study_key'] for s in state['studies'].values() if s['project_id']==project]
        snapshots=[];skipped=[]
        for study in dict.fromkeys(selected):
            owned(state,'studies',study,project)
            choices=[s for s in state['snapshots'].values() if s['project_id']==project and s['study_key']==study]
            if choices:snapshots.append(max(choices,key=lambda s:s['completed_at']))
            else:skipped.append(dict(study_key=study,reason='未完成复核，不导出草稿'))
        return dict(snapshot_ids=[s['snapshot_id'] for s in snapshots],skipped=skipped,
                    studies=len(snapshots),nodules=sum(s['counts']['confirmed'] for s in snapshots),
                    zero_confirmation=sum(s['counts']['confirmed']==0 for s in snapshots),dictionary_version='lungct-v1')

    def export_snapshots(self,project,snapshot_ids):
        state=self.repo.read();owned(state,'projects',project,project)
        if not isinstance(snapshot_ids,list) or not snapshot_ids or len(snapshot_ids)!=len(set(snapshot_ids)):raise ValueError('请选择不重复的已完成快照')
        snapshots=[owned(state,'snapshots',sid,project) for sid in snapshot_ids]
        if len({s['study_key'] for s in snapshots})!=len(snapshots):raise ValueError('同一次导出每例只能选择一个快照')
        for s in snapshots:
            if digest({k:v for k,v in s.items() if k!='sha256'})!=s['sha256']:raise ValueError('快照校验失败，拒绝导出')
        studies=[];nodules=[];audit=[]
        for s in snapshots:
            study=state['studies'][s['study_key']];run=s['run'];summary=s['counts']
            history=s.get('run_history',[]);last=history[-1] if history else None
            studies.append(dict(project_id=project,case_code=study['case_code'],subject_key=study['subject_key'],study_key=s['study_key'],series_key=s['series_key'],snapshot_id=s['snapshot_id'],analysis_mode=s['analysis_mode'],run_id=s['run_id'],run_state=run['state'] if run else (last['state'] if last else 'not_run'),ai_candidate_count=run['candidate_count'] if run and run['state']=='succeeded' else None,manual_count=summary['manual'],confirmed_count=summary['confirmed'],excluded_count=summary['excluded'],uncertain_count=summary['uncertain'],research_source=s['research_source'],synthetic=s['synthetic'],notice=NOTICE))
            for f in s['findings']:
                r=f['revision']
                if r['state']!='confirmed':continue
                nodules.append(dict(project_id=project,case_code=study['case_code'],study_key=s['study_key'],series_key=s['series_key'],snapshot_id=s['snapshot_id'],finding_id=f['finding_id'],label=f['label'],slice_key=r['slice_key'],center_lps_x=r['center_lps'][0],center_lps_y=r['center_lps'][1],center_lps_z=r['center_lps'][2],source=f['original']['source'],side=r['side'],lobe=r['lobe'],nodule_type=r['nodule_type'],long_mm=r['long_axis']['length_mm'] if r['long_axis'] else None,short_mm=r['short_axis']['length_mm'] if r['short_axis'] else None,missing_reason=r['missing_reason'],revision_id=r['revision_id'],notice=NOTICE))
            audit.append(dict(snapshot_id=s['snapshot_id'],study_key=s['study_key'],series_key=s['series_key'],analysis_mode=s['analysis_mode'],counts=s['counts'],snapshot_sha256=s['sha256'],
                observations=[dict(original=whitelist(f['original'],ORIGINAL_FIELDS),adopted_revision=revision(f['revision'])) for f in s['findings']],
                revisions=[revision(r) for r in s['revisions']],run=run_export(run),run_history=[run_export(r) for r in history]))
        export_id=uid('export');parent=self.root/'exports';parent.mkdir(exist_ok=True)
        temporary=parent/('.tmp-'+export_id);final=parent/export_id;temporary.mkdir()
        try:
            write_csv(temporary/'studies.csv',STUDY_FIELDS,studies);write_csv(temporary/'nodules.csv',NODULE_FIELDS,nodules)
            (temporary/'review.json').write_text(encoded(dict(schema_version='lungct-v1',notice=NOTICE,snapshots=audit)),encoding='utf-8')
            fields=list(dict.fromkeys(STUDY_FIELDS+NODULE_FIELDS))
            write_csv(temporary/'dictionary.csv',['field','label_zh','unit','enum','null_semantics'],[dict(field=f,label_zh=LABELS[f],unit='mm' if f.startswith('center_lps_') or f in ('long_mm','short_mm') else '',enum=ENUMS.get(f,''),null_semantics='未运行/不适用/未测量；CSV 空白，JSON null，不填零') for f in fields])
            hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in temporary.iterdir()}
            manifest=dict(export_id=export_id,project_id=project,dataset_version='lungct-v1',dictionary_version='lungct-v1',software_version=VERSION,created_at=now(),notice=NOTICE,snapshots=[dict(snapshot_id=s['snapshot_id'],sha256=s['sha256']) for s in snapshots],
                analysis=[dict(snapshot_id=s['snapshot_id'],analysis_mode=s['analysis_mode'],run=run_export(s['run'])) for s in snapshots],
                counts=dict(studies=len(studies),nodules=len(nodules),observations=sum(len(s['findings']) for s in snapshots)),files=hashes)
            (temporary/'manifest.json').write_text(encoded(manifest),encoding='utf-8')
            os.replace(temporary,final)
            with self.repo.transaction() as latest:latest['exports'][export_id]=dict(project_id=project,manifest=manifest)
            return manifest
        except BaseException:
            if temporary.exists():shutil.rmtree(temporary)
            raise

    def lookup_finding(self,project,study,finding,snapshot_id=None):
        state=self.repo.read();owned(state,'studies',study,project)
        choices=[s for s in state['snapshots'].values() if s['project_id']==project and s['study_key']==study and (snapshot_id is None or s['snapshot_id']==snapshot_id)]
        for snap in sorted(choices,key=lambda s:s['completed_at'],reverse=True):
            for f in snap['findings']:
                if f['finding_id']==finding or f['label']==finding:
                    series=owned(state,'series',snap['series_key'],project)
                    return dict(**locate(series,f['revision']['center_lps']),series_key=series['series_key'],snapshot_id=snap['snapshot_id'],draft_id=snap['draft_id'],finding_id=f['finding_id'])
        raise ValueError('未找到此项目/检查/快照下的观察编号')
