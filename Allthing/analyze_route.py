#!/usr/bin/env python3
"""
分析 polyline_points 的路线走向
"""
import math

# 起点和终点
start_point = [113.396127, 22.523973]
end_point = [113.389668, 22.517390]

# polyline_points 数据
polyline_points = [
    [113.39620364416, 22.522917096221],
    [113.39620364416, 22.522908750085],
    [113.39620364416, 22.522750173398],
    [113.39620364416, 22.52249978878],
    [113.39616771194, 22.522274442231],
    [113.39612279666, 22.522124210992],
    [113.39605093222, 22.522132557177],
    [113.39578144057, 22.52217428809],
    [113.39579042363, 22.52217428809],
    [113.39073296361, 22.522992211425],
    [113.38997838698, 22.523326056277],
    [113.38912499674, 22.523810129862],
    [113.38832550484, 22.521723593548],
    [113.38754397905, 22.519611986349],
    [113.38694211436, 22.517108061997],
    [113.38694211436, 22.517099715506],
    [113.38696008047, 22.517191526882],
    [113.38696906352, 22.517233259305],
    [113.38700499574, 22.517391842396],
    [113.38703194491, 22.517492000043],
    [113.38707686018, 22.517683968662],
    [113.38715770768, 22.517642236376],
    [113.38738228406, 22.517625543459],
    [113.38766075876, 22.517608850539],
    [113.38794821653, 22.517608850539],
    [113.38806499624, 22.517600504078],
    [113.38872075926, 22.517600504078],
    [113.38878364065, 22.517600504078],
    [113.38936753923, 22.517592157617],
    [113.38955618339, 22.517508692977],
    [113.38968194616, 22.517475307107]
]

def calculate_distance(p1, p2):
    """计算两点间的距离（米）"""
    lng_diff = (p2[0] - p1[0]) * 111000 * math.cos(math.radians((p1[1] + p2[1]) / 2))
    lat_diff = (p2[1] - p1[1]) * 111000
    return math.sqrt(lng_diff**2 + lat_diff**2)

def calculate_direction(p1, p2):
    """计算从p1到p2的方向"""
    lng_diff = p2[0] - p1[0]
    lat_diff = p2[1] - p1[1]
    
    if abs(lng_diff) < 0.00001 and abs(lat_diff) < 0.00001:
        return "静止"
    
    angle = math.degrees(math.atan2(lng_diff, lat_diff))
    
    if -22.5 <= angle < 22.5:
        return "北"
    elif 22.5 <= angle < 67.5:
        return "东北"
    elif 67.5 <= angle < 112.5:
        return "东"
    elif 112.5 <= angle < 157.5:
        return "东南"
    elif 157.5 <= angle <= 180 or -180 <= angle < -157.5:
        return "南"
    elif -157.5 <= angle < -112.5:
        return "西南"
    elif -112.5 <= angle < -67.5:
        return "西"
    else:
        return "西北"

print("=" * 60)
print("Polyline Points 路线分析")
print("=" * 60)

print(f"\n起点: {start_point}")
print(f"终点: {end_point}")
print(f"坐标点数量: {len(polyline_points)}")

# 计算总距离
total_distance = 0
for i in range(len(polyline_points) - 1):
    dist = calculate_distance(polyline_points[i], polyline_points[i+1])
    total_distance += dist

print(f"路线总距离: {total_distance:.0f} 米 ({total_distance/1000:.2f} 公里)")

# 分析各段走向
print("\n" + "=" * 60)
print("路线分段分析")
print("=" * 60)

segments = []
current_segment_start = 0
current_direction = None

for i in range(len(polyline_points) - 1):
    direction = calculate_direction(polyline_points[i], polyline_points[i+1])
    
    if current_direction is None:
        current_direction = direction
    elif direction != current_direction:
        segments.append({
            'start': current_segment_start,
            'end': i,
            'direction': current_direction,
            'points': i - current_segment_start
        })
        current_segment_start = i
        current_direction = direction

# 添加最后一段
segments.append({
    'start': current_segment_start,
    'end': len(polyline_points) - 1,
    'direction': current_direction,
    'points': len(polyline_points) - 1 - current_segment_start
})

for idx, seg in enumerate(segments):
    start_pt = polyline_points[seg['start']]
    end_pt = polyline_points[seg['end']]
    seg_dist = calculate_distance(start_pt, end_pt)
    
    print(f"\n第 {idx+1} 段: {seg['direction']}")
    print(f"  起点: [{start_pt[0]:.6f}, {start_pt[1]:.6f}]")
    print(f"  终点: [{end_pt[0]:.6f}, {end_pt[1]:.6f}]")
    print(f"  距离: {seg_dist:.0f} 米")
    print(f"  坐标点数: {seg['points']}")

# 关键转折点分析
print("\n" + "=" * 60)
print("关键转折点")
print("=" * 60)

for i in range(1, len(polyline_points) - 1):
    dir1 = calculate_direction(polyline_points[i-1], polyline_points[i])
    dir2 = calculate_direction(polyline_points[i], polyline_points[i+1])
    
    if dir1 != dir2 and dir1 != "静止" and dir2 != "静止":
        print(f"\n点 {i}: 方向从 {dir1} 转为 {dir2}")
        print(f"  坐标: [{polyline_points[i][0]:.6f}, {polyline_points[i][1]:.6f}]")

# 路线特征总结
print("\n" + "=" * 60)
print("路线特征总结")
print("=" * 60)

print("\n1. 整体走向:")
print(f"   从起点 {start_point} 到终点 {end_point}")
print(f"   大致方向: {calculate_direction(start_point, end_point)}")

print("\n2. 路线形状:")
print("   - 这是一个典型的公交/驾车路线")
print("   - 不是直线，而是沿着道路网络行进")
print("   - 包含多个转弯和方向变化")

print("\n3. 坐标点分布:")
print("   - 前9个点: 主要在起点附近，向南移动")
print("   - 第9-13点: 向西南方向长距离移动（可能是主干道）")
print("   - 第14-29点: 在终点附近，向东/东南方向移动")

print("\n4. 路线可视化建议:")
print("   - 在地图上绘制时，这些点会形成一条折线")
print("   - 折线会沿着实际道路走向")
print("   - 点与点之间用直线连接")

# 生成简单的ASCII可视化
print("\n" + "=" * 60)
print("简化版 ASCII 路线示意图")
print("=" * 60)

# 简化的网格可视化
grid_size = 20
min_lng = min(p[0] for p in polyline_points)
max_lng = max(p[0] for p in polyline_points)
min_lat = min(p[1] for p in polyline_points)
max_lat = max(p[1] for p in polyline_points)

grid = [[' ' for _ in range(grid_size)] for _ in range(grid_size)]

for pt in polyline_points:
    x = int((pt[0] - min_lng) / (max_lng - min_lng) * (grid_size - 1))
    y = int((pt[1] - min_lat) / (max_lat - min_lat) * (grid_size - 1))
    grid[grid_size - 1 - y][x] = '*'

# 标记起点和终点
start_x = int((start_point[0] - min_lng) / (max_lng - min_lng) * (grid_size - 1))
start_y = int((start_point[1] - min_lat) / (max_lat - min_lat) * (grid_size - 1))
end_x = int((end_point[0] - min_lng) / (max_lng - min_lng) * (grid_size - 1))
end_y = int((end_point[1] - min_lat) / (max_lat - min_lat) * (grid_size - 1))

grid[grid_size - 1 - start_y][start_x] = 'S'
grid[grid_size - 1 - end_y][end_x] = 'E'

print("\n   N")
print("   ^")
print("   |")
for row in grid:
    print("   " + " ".join(row))
print("   +------------------> E")
print(f"\n   S = 起点, E = 终点, * = 路线点")
print(f"   北方向朝上")
