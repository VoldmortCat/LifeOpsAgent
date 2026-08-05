import sys, os, json, logging
from pathlib import Path
ALLTHING_DIR = Path(__file__).resolve().parent.parent
os.chdir(str(ALLTHING_DIR))
sys.path.insert(0, str(ALLTHING_DIR))
logging.getLogger("chromadb").setLevel(logging.WARNING)
logging.getLogger("lifeops").setLevel(logging.WARNING)
from tools.knowledge.knowledge_tools import search_knowledge

# 先看一个结果的原始 JSON
result = search_knowledge.func(query="中山有什么海鲜餐厅推荐", max_results=3, city="中山", mode="vector")
data = json.loads(result)
r = data["results"][0]
print(f"confidence type: {type(r.get('confidence'))}")
print(f"confidence value: {r.get('confidence')}")
print(f"all keys: {list(r.keys())}")
print(f"full entry: {json.dumps(r, ensure_ascii=False, indent=2)[:500]}")