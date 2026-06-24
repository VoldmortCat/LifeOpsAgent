#!/usr/bin/env python3
"""
百度地图路线调试脚本
按照 agent 的实际使用方式调用，验证能否正确获取 polyline_points
"""
import sys
import os
import json

# 确保能找到 Allthing 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'Allthing'))


def main():
    print("=" * 60)
    print("百度地图路线调试工具")
    print("=" * 60)

    # 设置测试数据
    origin = "中山纪念图书馆"
    destination = "利和广场"
    mode = "transit"  # transit/driving/walking

    print(f"\n起点: {origin}")
    print(f"终点: {destination}")
    print(f"模式: {mode}\n")

    # 1. 获取 MCP 工具（和 agent 一样的方式）
    print("[1] 获取 MCP 工具...")
    try:
        from tools.maps.baidu_maps_mcp import get_baidu_mcp_tools
        mcp_tools = get_baidu_mcp_tools()

        if not mcp_tools:
            print("[ERROR] 未获取到 MCP 工具！")
            return

        # 找到 map_directions 和 map_geocode 工具
        map_directions = None
        map_geocode = None
        for tool in mcp_tools:
            if tool.name == "map_directions":
                map_directions = tool
            elif tool.name == "map_geocode":
                map_geocode = tool

        if not map_directions or not map_geocode:
            print(f"[ERROR] 未找到所需工具！")
            print(f"   map_directions: {'[OK]' if map_directions else '[ERROR]'}")
            print(f"   map_geocode: {'[OK]' if map_geocode else '[ERROR]'}")
            return

        print("[OK] MCP 工具获取成功\n")

    except Exception as e:
        print(f"[ERROR] 获取 MCP 工具失败: {e}")
        import traceback
        traceback.print_exc()
        return

    # 2. 先获取起点终点坐标
    print("[2] 获取起点终点坐标...")
    try:
        origin_result = map_geocode.invoke({"address": origin, "is_china": "true"})
        print(f"[OK] 起点解析结果: {origin_result[:100]}...")

        dest_result = map_geocode.invoke({"address": destination, "is_china": "true"})
        print(f"[OK] 终点解析结果: {dest_result[:100]}...\n")

    except Exception as e:
        print(f"[ERROR] 解析坐标失败: {e}")
        import traceback
        traceback.print_exc()
        return

    # 3. 调用路线规划
    print("[3] 调用路线规划...")
    try:
        # MCP工具返回的是tuple: (result, metadata)
        # origin_result 和 dest_result 已经是tuple，直接访问
        origin_list = origin_result[0]  # 第一个元素是list
        origin_data = json.loads(origin_list[0]["text"])
        
        dest_list = dest_result[0]
        dest_data = json.loads(dest_list[0]["text"])

        origin_loc = f"{origin_data['result']['location']['lat']},{origin_data['result']['location']['lng']}"
        dest_loc = f"{dest_data['result']['location']['lat']},{dest_data['result']['location']['lng']}"

        print(f"   起点坐标: {origin_loc}")
        print(f"   终点坐标: {dest_loc}")

        # 调用路线规划（和 agent 完全一样的方式）
        result_tuple = map_directions.invoke({
            "origin": origin_loc,
            "destination": dest_loc,
            "model": mode,
            "is_china": "true"
        })

        # MCP工具返回的是tuple: (result, metadata)，取第一个元素
        result = result_tuple[0][0]["text"]
        
        print(f"[OK] 路线规划调用成功！")
        print(f"   返回内容长度: {len(result)}")
        print(f"\n{'-'*60}")
        print(f"原始返回内容:")
        print(f"{'-'*60}")
        print(result)
        print(f"{'-'*60}\n")

        # 4. 使用 agent 相同的解析函数解析结果
        print("[4] 解析路线数据...")
        try:
            from graph.travel_node import _parse_mcp_route_response

            ak = os.environ.get("BAIDU_MAPS_API_KEY", "")
            map_data = _parse_mcp_route_response(result, ak)

            if not map_data:
                print("[ERROR] 解析失败！")
                return

            print("[OK] 解析成功！\n")

            # 5. 输出最终结果
            print("=" * 60)
            print("调试结果 - 最终数据")
            print("=" * 60)

            polyline = map_data.get("polyline_points", [])
            print(f"\n[POINTS] 点列表: {len(map_data.get('points', []))} 个")
            print(f"[POLYLINE] 路线坐标点: {len(polyline)} 个")

            if len(polyline) > 0:
                print(f"\n路线坐标样例:")
                print(f"  [0] {polyline[0]}")
                if len(polyline) > 1:
                    print(f"  [1] {polyline[1]}")
                if len(polyline) > 5:
                    print(f"  ... 跳过中间 {len(polyline)-4} 个点 ...")
                print(f"  [{len(polyline)-1}] {polyline[-1]}")

            print(f"\n{'='*60}")
            print(f"完整 mapData:")
            print(f"{'='*60}")
            print(json.dumps(map_data, ensure_ascii=False, indent=2))
            print(f"{'='*60}")

        except Exception as e:
            print(f"[ERROR] 解析结果失败: {e}")
            import traceback
            traceback.print_exc()

    except Exception as e:
        print(f"[ERROR] 调用路线规划失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
