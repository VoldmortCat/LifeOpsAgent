import sys, os, json, logging
from pathlib import Path
ALLTHING_DIR = Path(__file__).resolve().parent.parent
os.chdir(str(ALLTHING_DIR))
sys.path.insert(0, str(ALLTHING_DIR))
logging.getLogger("chromadb").setLevel(logging.WARNING)
logging.getLogger("lifeops").setLevel(logging.WARNING)
from tools.knowledge.knowledge_tools import search_knowledge

GENERIC = '带朋友吃遍中山'

def get_score(r):
    """提取综合得分"""
    conf = r.get('confidence', {})
    if isinstance(conf, dict):
        return conf.get('score', 0)
    return conf or 0

def get_vector_score(r):
    """提取纯向量相似度"""
    conf = r.get('confidence', {})
    if isinstance(conf, dict):
        return conf.get('breakdown', {}).get('vector_similarity', 0)
    return 0

queries = [
    ('乳鸽', '中山哪家乳鸽最好吃'),
    ('海鲜', '中山有什么海鲜餐厅推荐'),
    ('火锅', '中山有什么好吃的火锅店'),
    ('早茶', '中山哪里喝早茶好'),
    ('烧味', '中山好吃的烧鹅烧味'),
    ('东升镇', '东升镇有什么美食'),
    ('亲子', '中山带小孩去哪里吃饭'),
    ('石岐区', '石岐区有什么推荐餐厅'),
    ('小吃', '中山有什么特色小吃'),
    ('宵夜', '中山晚上有什么宵夜吃'),
    ('一日游', '中山一日游怎么安排吃'),
    ('约会', '中山适合情侣约会的餐厅'),
    ('素食', '中山有没有素食餐厅'),
    ('西餐', '中山有什么好的西餐厅'),
    ('简餐', '中山有什么快速午餐选择'),
]

print(f'{"意图":<8} {"泛化综合分":>10} {"泛化向量分":>10} {"泛化排名":>8} {"最佳专业条目":<28} {"专业综合分":>10} {"向量分差":>8}')
print('-' * 100)

summary = []
for intent, q in queries:
    result = search_knowledge.func(query=q, max_results=10, city='中山', mode='vector')
    data = json.loads(result)
    results = data.get('results', [])
    
    g_score = 0.0
    g_vec = 0.0
    g_rank = '-'
    best_title = ''
    best_score = 0.0
    best_vec = 0.0
    
    for i, r in enumerate(results):
        title = r.get('title', '')
        s = get_score(r)
        v = get_vector_score(r)
        if GENERIC in title:
            g_score = s
            g_vec = v
            g_rank = i + 1
        elif best_score == 0 and '避坑' not in title and GENERIC not in title:
            best_title = title[:28]
            best_score = s
            best_vec = v
    
    vgap = best_vec - g_vec
    print(f'{intent:<8} {g_score:>10.4f} {g_vec:>10.4f} {str(g_rank):>8} {best_title:<28} {best_score:>10.4f} {vgap:>+8.4f}')
    
    summary.append({
        'intent': intent,
        'g_vec': g_vec,
        'best_vec': best_vec,
        'g_rank': g_rank,
        'g_wins': g_vec > best_vec,
    })

# 统计
wins = [s for s in summary if s['g_wins']]
losses = [s for s in summary if not s['g_wins']]
avg_g_vec = sum(s['g_vec'] for s in summary) / len(summary)
avg_b_vec = sum(s['best_vec'] for s in summary) / len(summary)

print(f'\n=== 统计 ===')
print(f'  泛化条目平均向量相似度: {avg_g_vec:.4f}')
print(f'  专业条目平均向量相似度: {avg_b_vec:.4f}')
print(f'  泛化向量分更高: {len(wins)}/{len(summary)} 题')
print(f'  专业向量分更高: {len(losses)}/{len(summary)} 题')
if wins:
    print(f'  泛化霸榜的意图: {[s["intent"] for s in wins]}')
    for s in wins:
        print(f'    {s["intent"]}: 泛化={s["g_vec"]:.4f} vs 专业={s["best_vec"]:.4f} (排名#{s["g_rank"]})')