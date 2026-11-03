"""R-017 synthetic protocol acceptance; explicitly NOT inference evidence."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'/'lungct'))
from helpers import SOURCE,make_ct
from apps.lungct.service import Service


class R017ProtocolFixture:
    def metadata(self):
        return dict(name='SYNTHETIC_PROTOCOL_FIXTURE_NOT_AI',version='fixture-v1',weight_sha256=None,preprocessing_sha256='synthetic')

    def predict(self,volume,geometry,threshold):
        return dict(candidates=[dict(center_lps=p,box_lps=[p[0]-1,p[1]-1,p[2]-1,p[0]+1,p[1]+1,p[2]+1],score=.8)
                               for p in ([-6,-3,6],[6,-3,6],[-4,4,6])],model_to_lps=np.eye(4).tolist())


def run(output=None):
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);make_ct(root/'input')
        service=Service(root/'store',allowed_roots=[root],model=R017ProtocolFixture())
        project=service.create_project('R017-SYNTHETIC','TEST-READER')['project_id']
        series=service.import_study(project,root/'input',SOURCE)['series'][0]
        with service.repo.transaction() as state:state['studies'][series['study_key']]['case_code']='R-017'
        service.select_series(project,series['study_key'],series['series_key'])
        execution=service.start_run(project,series['series_key'],'fixture-request')
        for _ in range(100):
            execution=service.get_run(project,execution['run_id'])
            if execution['state'] in ('failed','succeeded'):break
            time.sleep(.02)
        assert execution['state']=='succeeded' and execution['candidate_count']==3
        draft=service.start_draft(project,series['series_key'],'TEST-READER',execution['run_id'])
        records=draft['findings'];manual=service.add_finding(project,draft['draft_id'],[4,5,6],'TEST-READER')
        for f,patch in zip(records,[{'state':'confirmed','missing_reason':'not_measured'},
                                    {'state':'excluded','reason':'false_positive'},
                                    {'state':'uncertain','reason':'insufficient_evidence'}]):
            service.revise_finding(project,draft['draft_id'],f['finding_id'],f['revision']['revision_id'],patch,'TEST-READER')
        current=service.get_draft(project,draft['draft_id'])
        try:service.complete_case(project,draft['draft_id'],current['version'],'TEST-READER',browsed=True)
        except ValueError as error:assert '待复核' in str(error)
        else:raise AssertionError('Pending manual observation must block completion')
        service.revise_finding(project,draft['draft_id'],manual['finding_id'],manual['revision']['revision_id'],{'state':'confirmed','missing_reason':'not_measured'},'TEST-READER')
        current=service.get_draft(project,draft['draft_id'])
        snapshot=service.complete_case(project,draft['draft_id'],current['version'],'TEST-READER',browsed=True)
        assert snapshot['counts']==dict(ai=3,manual=1,confirmed=2,excluded=1,uncertain=1,pending=0)
        package=service.export_snapshots(project,[snapshot['snapshot_id']])
        assert package['counts']==dict(studies=1,nodules=2,observations=4)
        if output:
            output=Path(output);output.mkdir(parents=True,exist_ok=True)
            for p in Path(package['output_directory']).iterdir():shutil.copy2(p,output/p.name)
        return dict(data='SYNTHETIC PROTOCOL ONLY',A04='BLOCKED, NOT RUN',counts=snapshot['counts'],export_counts=package['counts'],files=package['files'])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);args=parser.parse_args()
    print(json.dumps(run(args.output),ensure_ascii=False,indent=2))
