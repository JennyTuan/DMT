from pathlib import Path
from copy import deepcopy
import os
import numpy as np
from .core import uid, now, code, owned
from .repository import Repository
from .dicom_io import scan
from .geometry import from_dict
from .review import ReviewService
from .model import ModelService
from .export import ExportService


class Service(ReviewService,ModelService,ExportService):
    def __init__(self, root, *, allowed_roots=(), model=None):
        self.repo = Repository(root)
        self.root = self.repo.root
        self.allowed_roots = tuple(Path(p).resolve() for p in allowed_roots)
        self.model=model
        (self.root/'volumes').mkdir(exist_ok=True)

    def create_project(self, name, operator):
        item=dict(project_id=uid('project'),name=code(name),operator=code(operator),created_at=now(),selected_series=None)
        with self.repo.transaction() as state: state['projects'][item['project_id']]=item
        return item

    def state(self, project=None):
        state=self.repo.read()
        if project is None: return {'projects':list(state['projects'].values())}
        owned(state,'projects',project,project)
        return {name:[v for v in state[name].values() if v.get('project_id')==project]
                for name in ('studies','series','drafts','runs','snapshots')} | {'project':state['projects'][project], 'selected_series':state['projects'][project]['selected_series']}

    def import_study(self, project, directory, source):
        owned(self.repo.read(),'projects',project,project)
        scanned=scan(directory,project,source,self.allowed_roots)
        with self.repo.transaction() as state:
            owned(state,'projects',project,project)
            for summary,refs,volume in scanned:
                for ref in refs:
                    existing=state['sources'].get(ref['slice_key'])
                    if existing and existing['sha256']!=ref['sha256']: raise ValueError('UID_CONFLICT：同 UID 不同内容，已隔离本次导入')
                existing=state['series'].get(summary['series_key'])
                if existing and existing['input_sha256']!=summary['input_sha256']: raise ValueError('UID_CONFLICT：已登记序列内容发生变化')
            for summary,refs,volume in scanned:
                if summary['series_key'] in state['series']: continue
                if volume is not None:
                    path=self.root/'volumes'/f"{summary['series_key']}.npy"
                    temporary=path.with_suffix('.tmp')
                    with temporary.open('wb') as stream: np.save(stream,volume,allow_pickle=False)
                    os.replace(temporary,path)
                state['series'][summary['series_key']]=summary
                for ref in refs: state['sources'][ref['slice_key']]=ref
                state['studies'].setdefault(summary['study_key'],dict(project_id=project,study_key=summary['study_key'],subject_key=summary['subject_key'],case_code='R-'+str(len([x for x in state['studies'].values() if x['project_id']==project])+1).zfill(3),selected_series=None,status='draft'))
            return {'studies':[deepcopy(state['studies'][k]) for k in dict.fromkeys(s[0]['study_key'] for s in scanned)],
                    'series':[deepcopy(state['series'][s[0]['series_key']]) for s in scanned]}

    def select_series(self, project, study, series):
        with self.repo.transaction() as state:
            case=owned(state,'studies',study,project); selected=owned(state,'series',series,project)
            if selected['study_key']!=study: raise ValueError('序列与检查不一致')
            if not selected['eligible']: raise ValueError('质控未通过：'+', '.join(selected['qc_codes']))
            case['selected_series']=series
            state['projects'][project]['selected_series']=series
            return deepcopy(selected)

    def volume(self, project, series):
        selected=owned(self.repo.read(),'series',series,project)
        if not selected['eligible']: raise ValueError('质控未通过，不能定量或推理')
        return np.load(self.root/'volumes'/f'{series}.npy',allow_pickle=False,mmap_mode='r'),from_dict(selected['geometry'])
