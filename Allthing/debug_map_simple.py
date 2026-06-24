#!/usr/bin/env python3
"""
简化版百度地图调试脚本
直接测试方向 API
"""
import sys
import os
import json
import requests

# 设置 API Key - 请确保环境变量已设置
ak = os.environ.get("BAIDU_MAPS_API_KEY", "")

if not ak:
    print("❌ 请设置 BAIDU_MAPS_API_KEY 环境变量！")
    sys.exit(1)


def test_direction_v2():
    """测试 direction/v2 API（和 MCP 使用的相同）"""
    print("=" * 60)
    print("百度地图 direction/v2 API 测试")
    print("=" * 60)

    # 测试路线（中山纪念图书馆 -> 利和广场）
    origin = "22.523973,113.396127"
    destination = "22.517390,113.389668"

    print(f"\n起点: {origin}")
    print(f"终点: {destination}\n")

    for mode in ["transit", "driving", "walking"]:
        print(f"\n{'-'*60}")
        print(f"测试模式: {mode}")
        print(f"{'-'*60}")

        url = f"http://api.map.baidu.com/direction/v2/{mode}"
        params = {
            "origin": origin,
            "destination": destination,
            "ak": ak,
            "output": "json",
            "tactics": "11"  # 时间优先
        }

        try:
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()

            print(f"✅ API 调用成功！status={data.get('status')}")

            if data.get("status") != 0:
                print(f"❌ API 返回错误: {data.get('message')}")
                continue

            result = data.get("result", {})

            # 检查数据结构
            routes = result.get("routes", [])
            schemes = result.get("schemes", [])

            print(f"\n数据结构:")
            print(f"  - routes 数量: {len(routes)}")
            print(f"  - schemes 数量: {len(schemes)}")

            total_path_points = 0
            if routes:
                route = routes[0]
                steps = route.get("steps", [])
                print(f"  - steps 数量: {len(steps)}")

                # 检查 steps 结构
                for i, step in enumerate(steps):
                    print(f"    [{i}] step 类型: {type(step)}")
                    if isinstance(step, list):
                        print(f"       → 是 list，包含 {len(step)} 个子步骤")
                        for j, sub_step in enumerate(step):
                            path = sub_step.get("path", "")
                            if path:
                                point_count = len(path.split(";"))
                                print(f"         [{j}] 有 path，{point_count} 个点")
                                total_path_points += point_count
                    elif isinstance(step, dict):
                        path = step.get("path", "")
                        if path:
                            point_count = len(path.split(";"))
                            print(f"       有 path，{point_count} 个点")
                            total_path_points += point_count

                print(f"\n✅ 总计找到 {total_path_points} 个路径坐标点！")

            # 保存原始响应用于调试
            filename = f"debug_{mode}.json"
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"\n原始响应已保存到: {filename}")

        except Exception as e:
            print(f"❌ 请求失败: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    test_direction_v2()
