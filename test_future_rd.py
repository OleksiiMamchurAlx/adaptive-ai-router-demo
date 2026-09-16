import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent/'tools'))
from publication_guard import Blocked,scan,canonical

ROOT=Path(__file__).resolve().parent

def validate_research(value):
    approved=json.loads((ROOT/'publication-policy.json').read_text(encoding='utf-8'))['approved_research']
    scan('research.json',canonical(value))
    if canonical(value)!=canonical(approved): raise Blocked('UNREVIEWED_RESEARCH_CLAIM')
    schema=json.loads((ROOT/'projects/research.schema.json').read_text(encoding='utf-8'))
    if canonical(schema.get('const'))!=canonical(value) or schema.get('type')!='object': raise Blocked('RESEARCH_SCHEMA')
    if value['status']!='Research / architecture planning': raise Blocked('RESEARCH_STATUS')
    return True

class FutureResearchTests(unittest.TestCase):
    def setUp(self):
        self.value=json.loads((ROOT/'projects/future-unreal-automation-rd.json').read_text(encoding='utf-8'))
    def test_reviewed_planning_summary(self):
        self.assertTrue(validate_research(self.value))
        self.value['schema_version']=True
        with self.assertRaises(Blocked): validate_research(self.value)
    def test_raw_chat_blocked(self):
        self.value['messages']=[{'role':'user','content':'private conversation'}]
        with self.assertRaises(Blocked): validate_research(self.value)
    def test_private_path_blocked(self):
        self.value['summary']='C'+':'+chr(92)+'Users'+chr(92)+'Fixture'
        with self.assertRaises(Blocked): validate_research(self.value)
    def test_unproven_production_claim_blocked(self):
        self.value['summary']='A shipped commercial game'
        with self.assertRaises(Blocked): validate_research(self.value)
    def test_private_runtime_id_blocked(self):
        self.value['run_id']='private-fixture'
        with self.assertRaises(Blocked): validate_research(self.value)
    def test_evidence_links_exist(self):
        for name in self.value['evidence_links']: self.assertTrue((ROOT/name).is_file())
