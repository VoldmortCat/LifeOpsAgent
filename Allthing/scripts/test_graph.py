"""Subagents 模式测试：直接跑图看主 Agent 如何调子工具并合成回复"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graph.graph_builder import build_lifeops_graph
from graph.state import create_initial_state

graph = build_lifeops_graph()
config = {"configurable": {"thread_id": "test_subagents"}, "recursion_limit": 50}

print("=== 测试1：打招呼 → 主Agent直接回复（不调工具）===")
state = create_initial_state("你好，你是谁", "test")
r1 = graph.invoke(state, config)
msgs = r1.get("messages", [])
for m in msgs:
    role = m.__class__.__name__
    content = str(m.content)[:200] if hasattr(m, "content") else "(tool)"
    tc = f" + {len(m.tool_calls)} tool_calls" if hasattr(m, "tool_calls") and m.tool_calls else ""
    print(f"  [{role}]{tc}: {content}")

print("\n=== 测试2：查询账单 → 主Agent调工具 → 合成回复 ===")
from langchain_core.messages import HumanMessage
new_msgs = list(msgs) + [HumanMessage(content="帮我查一下4月的账单")]
r2 = graph.invoke({"messages": new_msgs}, config)
msgs2 = r2.get("messages", [])
for m in msgs2[len(msgs):]:
    role = m.__class__.__name__
    content = str(m.content)[:200] if hasattr(m, "content") else "(tool)"
    tc = f" + {len(m.tool_calls)} tool_calls" if hasattr(m, "tool_calls") and m.tool_calls else ""
    print(f"  [{role}]{tc}: {content}")
