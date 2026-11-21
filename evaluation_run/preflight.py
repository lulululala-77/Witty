import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import settings
from core import rag,llm,providers
settings.llm_key()
spec=providers.DRAFT_PROVIDERS[settings.draft_provider()]
print('provider',settings.draft_provider(),'model',settings.draft_model(),flush=True)
try:
 print('embedding',rag._encode(['连接测试']).shape,flush=True)
except Exception as e: print('embedding_error',str(e),flush=True)
try:
 print('llm',llm.chat(spec.protocol,settings.draft_base_url() or spec.base,settings.llm_key(),settings.draft_model(),'仅回复OK',['连接测试'],max_tokens=10,timeout=10,extra_body=spec.extra(False),headers=spec.headers),flush=True)
except Exception as e: print('llm_error',str(e),flush=True)
