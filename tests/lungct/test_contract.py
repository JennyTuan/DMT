import json
from pathlib import Path
import tempfile
import unittest
from jsonschema import Draft202012Validator, FormatChecker
from helpers import make_ct, SOURCE


class ContractTests(unittest.TestCase):
    def test_persisted_domain_entities_match_versioned_schema(self):
        from apps.lungct.service import Service
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);make_ct(root/'input');service=Service(root/'store',allowed_roots=[root])
            p=service.create_project('P','OP')['project_id'];s=service.import_study(p,root/'input',SOURCE)['series'][0]
            service.select_series(p,s['study_key'],s['series_key']);d=service.start_draft(p,s['series_key'],'OP')
            f=service.add_finding(p,d['draft_id'],[-6,-3,6],'OP')
            service.revise_finding(p,d['draft_id'],f['finding_id'],f['revision']['revision_id'],{'state':'confirmed','missing_reason':'not_measured'},'OP')
            d=service.get_draft(p,d['draft_id']);snapshot=service.complete_case(p,d['draft_id'],d['version'],'OP',browsed=True)
            package=service.export_snapshots(p,[snapshot['snapshot_id']])
            self.assertEqual(package['counts']['nodules'],1)
            schema=json.loads(Path('schemas/lungct/v1/domain.schema.json').read_text(encoding='utf-8'))
            Draft202012Validator.check_schema(schema)
            state=service.repo.read()
            for table,entity in [('projects','project'),('studies','study'),('series','series'),('drafts','draft'),('findings','finding'),('revisions','revision'),('snapshots','snapshot')]:
                validator=Draft202012Validator({**schema,'$ref':f'#/$defs/{entity}'},format_checker=FormatChecker())
                for item in state[table].values():
                    with self.subTest(entity=entity):validator.validate(item)

    def test_all_manual_operations_work_without_network(self):
        import socket
        from unittest.mock import patch
        with patch.object(socket,'create_connection',side_effect=AssertionError('network prohibited')):
            self.test_persisted_domain_entities_match_versioned_schema()


if __name__=='__main__':unittest.main()
