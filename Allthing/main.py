import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from langgraph.checkpoint.sqlite import SqliteSaver
from graph.graph_builder import LifeOpsGraphRouter
from llm.llm_registry import get_llm_registry
from prompts.version import get_all_versions
from graph.tool_tracer import reset_call_stats, get_call_stats


def handle_slash_commands(user_input: str):
    cmd = user_input.strip().lower()

    if cmd == "/rag":
        try:
            from monitoring.dashboard import show_rag_dashboard
            from monitoring.rag_logger import RAGMonitor
            show_rag_dashboard(RAGMonitor.get_instance())
        except ImportError:
            print("  ⚠️ 监控模块未安装，请先完成 P3 部署")
        return True, None

    if cmd == "/rag_test":
        yaml_path = "monitoring/test_cases.yml"
        if not os.path.exists(yaml_path):
            print(f"  ⚠️ 测试用例文件不存在：{yaml_path}")
            return True, None
        try:
            from monitoring.test_runner import load_test_cases, run_evaluation, generate_report
            cases = load_test_cases(yaml_path)
            report = run_evaluation(cases)
            generate_report(report)
        except ImportError:
            print("  ⚠️ 监控模块未安装，请先完成 P3 部署")
        return True, None

    if cmd == "/help":
        print("\n  📋 LifeOps 内置命令：")
        print("    /rag       查看 RAG 监控仪表盘")
        print("    /rag_test  运行 RAG 批量评估")
        print("    /stats     查看工具调用统计")
        print("    /model     查看当前模型配置")
        print("    /help      显示此帮助")
        print("    切换用户 <用户名>  切换对话身份")
        print("    quit/exit/q        退出程序\n")
        return True, None

    if cmd == "/stats":
        stats = get_call_stats()
        summary = stats.get_summary()
        print(f"\n  📊 工具调用统计（本会话）：")
        print(f"     总调用: {summary.get('total', 0)}")
        print(f"     成功: {summary.get('success_count', 0)}")
        print(f"     失败: {summary.get('failure_count', 0)}")
        print(f"     总耗时: {summary.get('total_duration_ms', 0):.0f}ms")
        by_tool = summary.get("by_tool", {})
        if by_tool:
            print(f"     按工具分组:")
            for name, info in by_tool.items():
                print(f"       {name}: {info['count']}次, 成功{info['success']}/{info['count']}, {info['total_ms']:.0f}ms")
        activations = summary.get("activations", 0)
        if activations:
            print(f"     降级策略激活: {activations}次")
        return True, None

    if cmd == "/model":
        registry = get_llm_registry()
        print(f"\n  🧠 当前模型配置:")
        for agent in ["main", "bill", "travel"]:
            info = registry.get_model_info(agent)
            print(f"     {agent}: {info['provider']}/{info['model']} (temperature={info['temperature']})")
        usage = registry.get_usage_report()
        if usage["total_calls"] > 0:
            print(f"\n  📊 用量统计:")
            print(f"     总调用: {usage['total_calls']}, 总Token: {usage['total_tokens']}")
        return True, None

    return False, None


if __name__ == "__main__":
    # 初始化 LLM 注册中心
    registry = get_llm_registry()
    model_info = {
        agent: registry.get_model_info(agent)["model"]
        for agent in ["main", "bill", "travel"]
    }
    prompt_versions = get_all_versions()

    print("=" * 60)
    print("🤖 LifeOps Agent V3.1 已启动")
    print("   Subagents 架构：主Agent全程驾驶，子Agent按需调用")
    print("   📊 账单管家  |  🗺️ 行程助手")
    print(f"   🧠 模型: main={model_info['main']}, bill={model_info['bill']}, travel={model_info['travel']}")
    print(f"   📝 提示词版本: {prompt_versions.get('assembler', '?')}")
    print("💡 输入 '/help' 查看内置命令")
    print("   输入 '/stats' 查看工具调用统计")
    print("   输入 quit/exit/q 退出")
    print("=" * 60)

    current_user = "default_user"
    os.makedirs("data/checkpoints", exist_ok=True)
    checkpoint_db = "data/checkpoints/lifeops_checkpoints.db"

    with SqliteSaver.from_conn_string(checkpoint_db) as checkpointer:
        router = LifeOpsGraphRouter(checkpointer=checkpointer)

        while True:
            user_input = input(f"\n[{current_user}] 您: ").strip()

            if user_input.lower() in ["quit", "exit", "q"]:
                print("🤖 再见！")
                break

            if user_input.lower().startswith("切换用户 "):
                new_user = user_input[len("切换用户 "):].strip()
                if new_user:
                    current_user = new_user
                    print(f"🤖 已切换到用户：{current_user}")
                continue

            handled, _ = handle_slash_commands(user_input)
            if handled:
                continue

            if not user_input:
                continue

            print("\n🤖 ", end="", flush=True)
            full_text = router.route(user_input, current_user)
            for char in full_text:
                print(char, end="", flush=True)
                time.sleep(0.03)
            print()
