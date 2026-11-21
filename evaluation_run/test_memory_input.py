"""Identity regressions, including the actual main.py save_memory model boundary."""
import ast
import json
import sys
import unittest
from pathlib import Path
from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from core.memory_input import build_memory_input, format_memory_messages, has_group_speakers
from core.memory_write_prompt import SYSTEM_PROMPT


class MemoryInputTests(unittest.TestCase):
    def setUp(self):
        self.call=Mock(return_value='{"save":false}')
        spec=SimpleNamespace(protocol='openai',base='test',default='test',headers=None,extra=lambda _:None)
        self.ns=dict(deque=deque,chats={},json=json,
            build_memory_input=build_memory_input,format_memory_messages=format_memory_messages,
            has_group_speakers=has_group_speakers,MEMORY_WRITE_SYSTEM_PROMPT=SYSTEM_PROMPT,
            llm=SimpleNamespace(chat=self.call),_api_key=lambda _: 'test',
            settings=SimpleNamespace(draft_provider=lambda:'test',draft_base_url=lambda:'',draft_model=lambda:'test'),
            providers=SimpleNamespace(DRAFT_PROVIDERS={'test':spec},LLM_ENV='test'))
        tree=ast.parse((ROOT/'main.py').read_text(encoding='utf-8'))
        funcs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'chat_of','auto_memory_text','save_memory'}]
        exec(compile(ast.Module(body=funcs,type_ignores=[]),'main.py','exec'),self.ns)

    def payload(self,title,messages):
        chat=self.ns['chat_of'](title)
        chat['history'].extend(messages);chat['pending_memory']=list(messages)
        self.ns['save_memory'](title,self.ns['auto_memory_text'](chat))
        return self.call.call_args.args[5][0]

    def test_single_chat_and_third_person(self):
        text=self.payload('周宁',[('her','我妹妹对花生过敏。',None),('me','我喜欢狗。',None)])
        self.assertIn('"her": "周宁"',text)
        self.assertIn('"speaker": "用户本人"',text)
        self.assertIn('我妹妹对花生过敏。',text)
        self.assertIn('current_date',text)

    def test_group_and_missing_speaker(self):
        text=self.payload('周末活动群',[('her','我不吃香菜。','小林'),('her','我怕猫。','小周'),('her','这条名字没识别到。',None),('me','我喜欢狗。',None)])
        self.assertIn('群聊（检测到成员名称）',text)
        self.assertIn('"speaker": "小林"',text)
        self.assertIn('"speaker": "小周"',text)
        self.assertIn('"speaker": "未知发言人"',text)
        self.assertNotIn('"speaker": "周末活动群"',text)

    def test_unknown_title_not_used_as_name(self):
        text=self.payload('当前会话',[('her','我不吃香菜。',None)])
        self.assertIn('"contact_nickname": "未知"',text)

    def test_trimming_preserves_speaker(self):
        text=format_memory_messages([('her','旧消息'*100,'甲'),('her','新消息','乙')],is_group=True,max_chars=90)
        messages=[json.loads(line) for line in text.splitlines()]
        self.assertEqual(messages,[{'role':'her','speaker':'乙','text':'新消息'}])

    def test_manual_save_also_has_metadata(self):
        self.ns['save_memory']('周宁','her: 我不吃香菜。')
        self.assertIn('"contact_nickname": "周宁"',self.call.call_args.args[5][0])

if __name__=='__main__':unittest.main()
