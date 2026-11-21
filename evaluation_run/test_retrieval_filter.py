import sys,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from contextlib import closing
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import rag,retrieval_filter as rf

class FilterTests(unittest.TestCase):
 def setUp(self):
  for p in [patch('app.settings.llm_key',return_value='test'),patch('core.jev_client._api_key',return_value='test')]:
   p.start();self.addCleanup(p.stop)
  self.c=[{'id':1,'content':'记忆一'},{'id':2,'content':'记忆二'}]
 def test_empty_skips_model(self):
  with patch('core.llm.chat') as model:
   self.assertEqual(rf.filter_candidates('消息',[])['status'],'no_candidates');model.assert_not_called()
 def test_one_batch_selects_only_ids(self):
  with patch('core.llm.chat',return_value='{"keep_ids":[2]}') as model:
   r=rf.filter_candidates('消息',self.c);self.assertEqual(r['keep_ids'],[2]);model.assert_called_once()
 def test_valid_empty(self):
  with patch('core.llm.chat',return_value='{"keep_ids":[]}'):
   self.assertEqual(rf.filter_candidates('我累了',self.c)['status'],'ok')
 def test_explicit_speaker_passed_without_rewriting_query(self):
  import json
  with patch('core.llm.chat',return_value='{"keep_ids":[1]}') as model:
   rf.filter_candidates('我喜欢这个',self.c,query_speaker='何川')
   payload=json.loads(model.call_args.args[5][0])
   self.assertEqual(payload['query_speaker'],'何川');self.assertEqual(payload['query'],'我喜欢这个')
 def test_invalid_responses_fail_closed(self):
  for raw in ['{"keep_ids":[3]}','{"keep_ids":[true]}','{"keep_ids":[1,1]}','{"keep_ids":[1],"keep_ids":[]}','{"keep_ids":[],"extra":1}','[]','not json']:
   with self.subTest(raw=raw),patch('core.llm.chat',return_value=raw):
    r=rf.filter_candidates('消息',self.c);self.assertEqual(r['status'],'error');self.assertEqual(r['keep_ids'],[])
 def test_service_error_is_not_semantic_empty(self):
  with patch('core.llm.chat',side_effect=RuntimeError('offline')):
   self.assertEqual(rf.filter_candidates('消息',self.c)['status'],'error')
 def test_production_retrieve_filters_scope_and_keeps_original_text(self):
  with tempfile.TemporaryDirectory() as d,patch.object(rag,'DB_PATH',Path(d)/'test.sqlite3'),patch.object(rag,'_encode',return_value=np.array([[1.,0.]],dtype=np.float32)):
   with closing(rag._connect()) as c,c:
    for person,expiry,text in [('甲',None,'甲对花生过敏。'),('甲',None,'甲的弟弟明天坐火车来。'),('乙',None,'乙的弟弟明天坐火车来。'),('甲','2000-01-01','甲昨天在车站等人。')]:
     c.execute('INSERT INTO memories(dimension,contact,category,content,importance,embedding,expires_at) VALUES(?,?,?,?,?,?,?)',('other_person',person,'fact',text,3,np.array([1.,0.],dtype=np.float32).tobytes(),expiry))
   trace={}
   with patch('core.llm.chat',return_value='{"keep_ids":[2]}') as model:
    text=rag.retrieve('弟弟的火车',dimension='other_person',contact='甲',trace=trace)
    self.assertEqual(text,'- [fact] 甲的弟弟明天坐火车来。')
    self.assertEqual({c['id'] for c in trace['candidates']},{1,2});model.assert_called_once()
   with patch('core.llm.chat',return_value='invalid'):
    self.assertEqual(rag.retrieve('弟弟',contact='甲'), '')

if __name__=='__main__':unittest.main()
