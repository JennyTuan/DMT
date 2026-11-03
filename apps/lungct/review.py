"""Append-only human review, physical lines and immutable case snapshots."""
from copy import deepcopy
import numpy as np
from .core import code, uid, now, owned, digest
from .geometry import from_dict, patient_to_pixel

REASONS={'false_positive','duplicate','artifact','insufficient_evidence','withdrawn','correction','not_measured','not_visible','unreliable_boundary','location_changed'}
FIELDS={'state','reason','center_lps','slice_key','side','lobe','nodule_type','long_axis','short_axis','missing_reason'}


def current(state,draft):
    return [dict(finding_id=fid,label=f'N-{i+1:03d}',original=deepcopy(state['findings'][fid]),
                 revision=deepcopy(state['revisions'][rid])) for i,(fid,rid) in enumerate(draft['heads'].items())]


def counts(records):
    result=dict(ai=0,manual=0,confirmed=0,excluded=0,uncertain=0,pending=0)
    for item in records:
        result[item['original']['source']]+=1;result[item['revision']['state']]+=1
    return result


def editable(state,project,did):
    draft=owned(state,'drafts',did,project)
    if draft['status']=='completed':raise ValueError('病例已完成，请重新打开为新草稿')
    return draft


def append_revision(state,draft,fid,previous,values,operator,action):
    rid=uid('revision')
    record={**values,'revision_id':rid,'finding_id':fid,'previous_revision_id':previous,
            'operator':code(operator),'at':now(),'action':action}
    state['revisions'][rid]=record;draft['heads'][fid]=rid;draft['version']+=1
    state['studies'][draft['study_key']]['status']='reviewing'
    return deepcopy(record)


def create_finding(state,draft,point,operator,source='manual',run_id=None,box=None,score=None):
    series=state['series'][draft['series_key']];g=from_dict(series['geometry'])
    index,x,y=patient_to_pixel(g,point,require_plane=(source=='manual'))
    source_point=list(g.pixel_to_patient(index,x,y))
    fid=uid('finding')
    state['findings'][fid]=dict(finding_id=fid,project_id=draft['project_id'],series_key=draft['series_key'],
        source=source,run_id=run_id,center_lps=list(point),slice_key=series['slice_keys'][index],box_lps=box,score=score)
    values=dict(state='pending',reason=None,center_lps=source_point,slice_key=series['slice_keys'][index],
                side='unknown',lobe='unknown',nodule_type='unknown',long_axis=None,short_axis=None,missing_reason=None)
    append_revision(state,draft,fid,None,values,operator,'add')
    return next(f for f in current(state,draft) if f['finding_id']==fid)


def validate_revision(revision,series):
    if revision['state'] not in ('pending','confirmed','excluded','uncertain'):raise ValueError('复核状态无效')
    if revision['side'] not in ('left','right','unknown'):raise ValueError('侧别无效')
    if revision['lobe'] not in ('RUL','RML','RLL','LUL','LLL','unknown'):raise ValueError('肺叶无效')
    if revision['nodule_type'] not in ('solid','part_solid','ground_glass','unknown'):raise ValueError('结节类型无效')
    if (revision['side']=='right' and revision['lobe'].startswith('L')) or (revision['side']=='left' and revision['lobe'].startswith('R')):raise ValueError('侧别与肺叶不一致')
    for k in ('reason','missing_reason'):
        if revision[k] is not None and revision[k] not in REASONS:raise ValueError('请选择结构化原因，不接受自由病史')
    if revision['state'] in ('excluded','uncertain') and not revision['reason']:raise ValueError('排除或存疑必须选择原因')
    g=from_dict(series['geometry']);index,_,_=patient_to_pixel(g,revision['center_lps'],require_plane=True)
    if revision['slice_key']!=series['slice_keys'][index]:raise ValueError('中心点与源切片引用不一致')
    for axis in ('long_axis','short_axis'):
        value=revision[axis]
        if value is None:continue
        ends=np.asarray(value.get('endpoints') if isinstance(value,dict) else value,dtype=float)
        if ends.shape!=(2,3) or not np.isfinite(ends).all():raise ValueError('径线需要两个有限 LPS 端点')
        if any(patient_to_pixel(g,p,require_plane=True)[0]!=index for p in ends):raise ValueError('径线端点必须在同一原始层面')
        length=float(np.linalg.norm(ends[1]-ends[0]))
        if length<=0:raise ValueError('径线长度必须大于零')
        revision[axis]=dict(endpoints=ends.tolist(),length_mm=length,slice_key=revision['slice_key'],method='manual_axial_lps')
    long,short=revision['long_axis'],revision['short_axis']
    if short:
        if not long:raise ValueError('先绘制长径，再绘制短径')
        if short['length_mm']>long['length_mm']+.001:raise ValueError('短径超过长径，请重画')
        a=np.diff(long['endpoints'],axis=0)[0];b=np.diff(short['endpoints'],axis=0)[0]
        if abs(a @ b)/(long['length_mm']*short['length_mm'])>.01:raise ValueError('短径必须与长径垂直')


class ReviewService:
    def finding_history(self,project,draft,finding):
        state=self.repo.read();item=owned(state,'drafts',draft,project)
        if finding not in item['heads']:raise ValueError('观察不属于当前草稿')
        rid=item['heads'][finding];chain=[]
        while rid:
            revision=state['revisions'][rid];chain.append(deepcopy(revision));rid=revision['previous_revision_id']
        return chain

    def start_draft(self,project,series,operator,run_id=None):
        code(operator)
        with self.repo.transaction() as state:
            s=owned(state,'series',series,project)
            if not s['eligible'] or state['studies'][s['study_key']]['selected_series']!=series:raise ValueError('请先确认有效分析序列')
            for d in state['drafts'].values():
                if d['project_id']==project and d['series_key']==series and d['run_id']==run_id and d['status']!='completed':
                    return {**deepcopy(d),'findings':current(state,d)}
            run=None
            if run_id:
                run=owned(state,'runs',run_id,project)
                if run['series_key']!=series or run['state']!='succeeded' or not run['complete']:raise ValueError('运行未完整成功，不能建立 AI 复核分支')
            did=uid('draft');draft=dict(draft_id=did,project_id=project,study_key=s['study_key'],series_key=series,
                run_id=run_id,analysis_mode='ai' if run_id else 'manual',operator=operator,status='reviewing',heads={},version=0,created_at=now())
            state['drafts'][did]=draft;state['studies'][s['study_key']]['status']='reviewing'
            if run:
                for fid in run['finding_ids']:
                    draft['heads'][fid]=run['initial_revisions'][fid]
            return {**deepcopy(draft),'findings':current(state,draft)}

    def get_draft(self,project,draft):
        state=self.repo.read();item=owned(state,'drafts',draft,project)
        return {**item,'findings':current(state,item),'counts':counts(current(state,item))}

    def add_finding(self,project,draft,point,operator):
        with self.repo.transaction() as state:
            item=editable(state,project,draft)
            return create_finding(state,item,point,operator)

    def revise_finding(self,project,draft,finding,expected_revision_id,patch,operator):
        with self.repo.transaction() as state:
            item=editable(state,project,draft)
            if finding not in item['heads']:raise ValueError('观察不属于当前草稿')
            if item['heads'][finding]!=expected_revision_id:raise ValueError('修订已过期，请刷新后重试')
            if not isinstance(patch,dict) or not patch or set(patch)-FIELDS:raise ValueError('修订字段不在白名单中')
            values={k:deepcopy(state['revisions'][expected_revision_id][k]) for k in FIELDS}
            if ('center_lps' in patch and patch['center_lps']!=values['center_lps']) or ('slice_key' in patch and patch['slice_key']!=values['slice_key']):
                values.update(long_axis=None,short_axis=None,missing_reason='location_changed')
            values.update(deepcopy(patch))
            validate_revision(values,state['series'][item['series_key']])
            append_revision(state,item,finding,expected_revision_id,values,operator,'revise')
            return next(f for f in current(state,item) if f['finding_id']==finding)

    def undo_finding(self,project,draft,finding,expected_revision_id,operator):
        with self.repo.transaction() as state:
            item=editable(state,project,draft)
            if item['heads'].get(finding)!=expected_revision_id:raise ValueError('修订已过期，请刷新')
            previous=state['revisions'][expected_revision_id]['previous_revision_id']
            if previous is None:raise ValueError('初始观察无法物理删除；可选择排除/撤回')
            values={k:deepcopy(state['revisions'][previous][k]) for k in FIELDS}
            append_revision(state,item,finding,expected_revision_id,values,operator,'undo')
            return next(f for f in current(state,item) if f['finding_id']==finding)

    def complete_case(self,project,draft,expected_version,operator,*,browsed=False,confirm_zero=False):
        with self.repo.transaction() as state:
            item=editable(state,project,draft)
            if type(expected_version) is not int or item['version']!=expected_version:raise ValueError('草稿已过期，请刷新')
            if browsed is not True:raise ValueError('请确认已浏览整例原始影像')
            records=current(state,item);summary=counts(records)
            if summary['pending']:raise ValueError('仍有待复核观察，不能完成')
            if summary['confirmed']==0 and confirm_zero is not True:raise ValueError('没有已确认结节，请明确确认零确认结案')
            for record in records:
                r=record['revision'];validate_revision(r,state['series'][item['series_key']])
                if r['state']=='confirmed' and (r['long_axis'] is None or r['short_axis'] is None) and not r['missing_reason']:raise ValueError('缺测径线必须填写结构化缺测原因')
            revisions={}
            for rid in item['heads'].values():
                while rid:
                    r=state['revisions'][rid];revisions[rid]=deepcopy(r);rid=r['previous_revision_id']
            sid=uid('snapshot');run=deepcopy(state['runs'].get(item['run_id']))
            snapshot=dict(snapshot_id=sid,project_id=project,study_key=item['study_key'],series_key=item['series_key'],
                draft_id=draft,run_id=item['run_id'],analysis_mode=item['analysis_mode'],completed_at=now(),operator=code(operator),
                findings=records,revisions=list(revisions.values()),counts=summary,run=run,
                heads=deepcopy(item['heads']),research_source=state['series'][item['series_key']]['source']['research_source'],
                synthetic=state['series'][item['series_key']]['synthetic'],
                run_history=[deepcopy(r) for r in state['runs'].values() if r['project_id']==project and r['series_key']==item['series_key']])
            snapshot['sha256']=digest(snapshot)
            state['snapshots'][sid]=snapshot;item['status']='completed';item['snapshot_id']=sid
            state['studies'][item['study_key']]['status']='completed'
            return deepcopy(snapshot)

    def reopen_case(self,project,snapshot,operator):
        with self.repo.transaction() as state:
            snap=owned(state,'snapshots',snapshot,project);did=uid('draft')
            draft=dict(draft_id=did,project_id=project,study_key=snap['study_key'],series_key=snap['series_key'],
                run_id=snap['run_id'],analysis_mode=snap['analysis_mode'],operator=code(operator),status='reviewing',
                heads=deepcopy(snap['heads']),version=0,created_at=now(),reopened_from=snapshot)
            state['drafts'][did]=draft;state['studies'][snap['study_key']]['status']='reviewing'
            return {**deepcopy(draft),'findings':current(state,draft)}
