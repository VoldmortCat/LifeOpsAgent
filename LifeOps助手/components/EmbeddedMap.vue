<template>
	<view class="embedded-map" v-if="mapData">
		<!-- 地图头部：可折叠 -->
		<view class="map-header" @click="expanded = !expanded">
			<view class="map-header-left">
				<text class="map-header-icon">{{ headerIcon }}</text>
				<text class="map-header-title">{{ headerTitle }}</text>
			</view>
			<text class="map-header-arrow">{{ expanded ? '收起 ▲' : '展开地图 ▼' }}</text>
		</view>

		<!-- 地图区域 -->
		<view v-if="expanded" class="map-body">
			<!-- H5 模式：Baidu Maps JS API 自建容器 -->
			<!-- #ifdef H5 -->
			<view :id="mapContainerId" class="map-view-h5"></view>
			<!-- #endif -->
			<!-- 小程序模式：uni-app map 组件 -->
			<!-- #ifndef H5 -->
			<map
				class="map-view"
				:longitude="centerLng"
				:latitude="centerLat"
				:scale="mapData.zoom || 15"
				:markers="markers"
				:polyline="polyline"
				show-location
				@markertap="onMarkerTap"
				style="width: 100%; height: 280px;"
			></map>
			<!-- #endif -->

			<!-- 单条路线信息卡片 -->
			<view v-if="mapData.type === 'route' && mapData.route" class="route-info-card">
				<view class="route-stats">
					<view class="route-stat-item">
						<text class="route-stat-icon">{{ modeIcon }}</text>
						<text class="route-stat-label">{{ modeText }}</text>
					</view>
					<view class="route-stat-divider"></view>
					<view class="route-stat-item">
						<text class="route-stat-value">{{ mapData.route.duration }}</text>
					</view>
					<view class="route-stat-divider"></view>
					<view class="route-stat-item">
						<text class="route-stat-value">{{ mapData.route.distance }}</text>
					</view>
				</view>
				<view class="route-steps" v-if="mapData.route.steps && mapData.route.steps.length > 0">
					<view v-for="(step, sIdx) in mapData.route.steps.slice(0, 3)" :key="sIdx" class="step-item">
						<text class="step-num">{{ sIdx + 1 }}</text>
						<text class="step-text">{{ step }}</text>
					</view>
				</view>
				<view class="nav-btn" @click="openSystemNav">
					<text>🧭 一键导航</text>
				</view>
			</view>

			<!-- 多条路线信息卡片 -->
			<view v-if="mapData.type === 'multi_route' && mapData.route_infos" class="route-info-card">
				<view v-for="(info, rIdx) in mapData.route_infos" :key="rIdx" class="multi-route-item">
					<view class="route-stats">
						<view class="route-stat-item">
							<text class="route-stat-icon">{{ multiRouteModeIcon(info.mode) }}</text>
							<text class="route-stat-label">{{ info.dest_name }}</text>
						</view>
						<view class="route-stat-divider"></view>
						<view class="route-stat-item">
							<text class="route-stat-value">{{ info.duration }}</text>
						</view>
						<view class="route-stat-divider"></view>
						<view class="route-stat-item">
							<text class="route-stat-value">{{ info.distance }}</text>
						</view>
					</view>
					<view v-if="rIdx < mapData.route_infos.length - 1" class="route-separator"></view>
				</view>
			</view>

			<!-- 多模式路线卡片（驾车/公交/步行切换） -->
			<view v-if="mapData.type === 'multi_mode_route' && modeRoutes.length > 0" class="route-info-card">
				<!-- 出行方式切换 tabs -->
				<view class="mode-tabs">
					<view
						v-for="(mr, mIdx) in modeRoutes"
						:key="mr.mode"
						class="mode-tab"
						:class="{ 'mode-tab-active': mIdx === activeModeIndex }"
						@click="activeModeIndex = mIdx"
					>
						<text class="mode-tab-icon">{{ modeTabIcon(mr.mode) }}</text>
						<text class="mode-tab-label">{{ modeTabLabel(mr.mode) }}</text>
					</view>
				</view>
				<!-- 当前选中模式的路线信息 -->
				<view class="route-stats">
					<view class="route-stat-item">
						<text class="route-stat-icon">{{ activeModeIcon }}</text>
						<text class="route-stat-label">{{ activeModeLabel }}</text>
					</view>
					<view class="route-stat-divider"></view>
					<view class="route-stat-item">
						<text class="route-stat-value">{{ activeModeRoute.duration }}</text>
					</view>
					<view class="route-stat-divider"></view>
					<view class="route-stat-item">
						<text class="route-stat-value">{{ activeModeRoute.distance }}</text>
					</view>
				</view>
				<view class="route-steps" v-if="activeModeRoute.steps && activeModeRoute.steps.length > 0">
					<view v-for="(step, sIdx) in activeModeRoute.steps.slice(0, 3)" :key="sIdx" class="step-item">
						<text class="step-num">{{ sIdx + 1 }}</text>
						<text class="step-text">{{ step }}</text>
					</view>
				</view>
				<view class="nav-btn" @click="openSystemNav">
					<text>🧭 一键导航</text>
				</view>
			</view>

			<!-- POI 列表 -->
			<view v-if="mapData.type === 'poi_list' && mapData.points && mapData.points.length > 0" class="poi-list">
				<view
					v-for="(point, pIdx) in mapData.points"
					:key="pIdx"
					class="poi-item"
					@click="centerOnPoint(point)"
				>
					<view class="poi-item-left">
						<text class="poi-tag" v-if="point.tag" :class="'tag-' + getTagClass(point.tag)">
							{{ getTagLabel(point.tag) }}
						</text>
						<text class="poi-name">{{ point.name }}</text>
					</view>
					<view class="poi-item-right">
						<text v-if="point.rating" class="poi-rating">⭐ {{ point.rating }}</text>
						<text v-if="point.price" class="poi-price">{{ point.price }}</text>
					</view>
				</view>
			</view>
		</view>
	</view>
</template>

<script setup>
	import { ref, computed, watch, onMounted, nextTick } from 'vue'

	const props = defineProps({
		mapData: {
			type: Object,
			default: null
		}
	})

	const expanded = ref(false)
	const activeModeIndex = ref(0) // 多模式路线当前选中的 mode tab 索引
	const mapContainerId = ref('baidu-map-' + Math.random().toString(36).slice(2, 8))
	let bmapInstance = null
	let lineLayer = null // LineLayer 实例（路线纹理描边）

	// ============ H5 百度地图初始化（BMapGL WebGL版）=============
	// #ifdef H5
	function initH5Map() {
		if (!props.mapData) return
		if (!window.BMapGL) { console.warn('[Map] BMapGL 未加载'); return }
		nextTick(() => {
			const el = document.getElementById(mapContainerId.value)
			if (!el) return
			// 清空旧内容
			while (el.firstChild) {
				el.removeChild(el.firstChild)
			}
			// 重置实例
			bmapInstance = null
			lineLayer = null

			const center = props.mapData.center || [113.38, 22.52]
			bmapInstance = new BMapGL.Map(el)
			bmapInstance.centerAndZoom(new BMapGL.Point(center[0], center[1]), props.mapData.zoom || 14)
			bmapInstance.enableScrollWheelZoom()
			updateH5Map()
		})
	}

	function createStartEndLabel(pt, text, color) {
		const label = new BMapGL.Label(text, {
			position: pt,
			offset: new BMapGL.Pixel(-14, -14)
		})
		label.setStyle({
			color: '#fff',
			backgroundColor: color,
			border: '2px solid #fff',
			borderRadius: '50%',
			padding: '6px 8px',
			fontSize: '13px',
			fontWeight: 'bold',
			boxShadow: '0 2px 6px rgba(0,0,0,0.3)',
			lineHeight: '16px',
			whiteSpace: 'nowrap'
		})
		return label
	}

	// 创建自定义 SVG 图钉图标（起点=绿色，终点=红色）
	function createPinIcon(color, labelText) {
		const fillColor = color === 'green' ? '#4CAF50' : '#F44336'
		const svgStr = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="46" viewBox="0 0 32 46">'
			+ '<defs><filter id="ds" x="-20%" y="-20%" width="140%" height="140%">'
			+ '<feDropShadow dx="0" dy="2" stdDeviation="2" flood-color="#000" flood-opacity="0.25"/>'
			+ '</filter></defs>'
			+ '<path d="M16 0C7.164 0 0 7.164 0 16c0 12 16 30 16 30s16-18 16-30C32 7.164 24.836 0 16 0z"'
			+ ' fill="' + fillColor + '" filter="url(#ds)"/>'
			+ '<circle cx="16" cy="15" r="8" fill="#fff"/>'
			+ '<text x="16" y="19" text-anchor="middle" font-size="11" font-weight="bold" fill="' + fillColor + '">' + labelText + '</text>'
			+ '</svg>'
		return new BMapGL.Icon(
			'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svgStr))),
			new BMapGL.Size(32, 46),
			{ anchor: new BMapGL.Size(16, 44) }
		)
	}

	function addArrowsToPolyline(pathPoints) {
		if (pathPoints.length < 2) return
		const step = Math.max(1, Math.floor(pathPoints.length / 8))
		for (let i = step; i < pathPoints.length - step / 2; i += step) {
			const start = pathPoints[i - Math.floor(step / 2)]
			const end = pathPoints[Math.min(i + Math.floor(step / 2), pathPoints.length - 1)]
			if (!start || !end) continue
			const midLng = (start.lng + end.lng) / 2
			const midLat = (start.lat + end.lat) / 2
			let angle = Math.atan2(end.lat - start.lat, end.lng - start.lng) * 180 / Math.PI
			const svgStr = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"><path d="M0 8 L16 0 L11 8 L16 16 Z" fill="#007aff"/></svg>`
			const icon = new BMapGL.Icon(
				'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svgStr))),
				new BMapGL.Size(16, 16),
				{ anchor: new BMapGL.Size(8, 8) }
			)
			const arrowMarker = new BMapGL.Marker(new BMapGL.Point(midLng, midLat), { 
				icon: icon, 
				enableDragging: false, 
				zIndex: 100,
				rotation: angle
			})
			bmapInstance.addOverlay(arrowMarker)
		}
	}

	function updateH5Map() {
		if (!bmapInstance || !props.mapData) return
		if (!window.BMapGL) return
		console.log('[Map] updateH5Map 调用, mapData:', JSON.stringify(props.mapData).slice(0, 400))
		bmapInstance.clearOverlays()
		// 移除旧的 LineLayer
		if (lineLayer) {
			bmapInstance.removeNormalLayer(lineLayer)
			lineLayer = null
		}

		const points = props.mapData.points || []
		console.log('[Map] points 数量:', points.length, points)
		if (points.length === 0) {
			console.warn('[Map] 没有坐标点数据')
			return
		}

		const bmapPoints = []
		points.forEach((p) => {
			const pt = new BMapGL.Point(p.lng, p.lat)
			bmapPoints.push(pt)
			
			if (p.tag === '起点') {
				// 绿色图钉 + "起" 标签
				const startIcon = createPinIcon('green', '起')
				const marker = new BMapGL.Marker(pt, { icon: startIcon, zIndex: 200 })
				bmapInstance.addOverlay(marker)
			} else if (p.tag === '终点') {
				// 红色图钉 + "终" 标签
				const endIcon = createPinIcon('red', '终')
				const marker = new BMapGL.Marker(pt, { icon: endIcon, zIndex: 200 })
				bmapInstance.addOverlay(marker)
			} else {
				const marker = new BMapGL.Marker(pt)
				bmapInstance.addOverlay(marker)
				if (p.name) {
					const label = new BMapGL.Label(p.name, { position: pt, offset: new BMapGL.Pixel(20, -10) })
					label.setStyle({ border: 'none', background: 'rgba(255,255,255,0.9)', padding: '2px 6px', borderRadius: '4px', fontSize: '12px' })
					bmapInstance.addOverlay(label)
				}
			}
		})

		if (props.mapData.type === 'route') {
			// 单条路线
			_drawH5Polyline(props.mapData.polyline_points || [], points)
		} else if (props.mapData.type === 'multi_mode_route') {
			// 多模式路线：只绘制当前选中模式的路线
			const activePts = activeModeRoute.value.polyline_points || []
			_drawH5Polyline(activePts, points)
		} else if (props.mapData.type === 'multi_route') {
			// 多条路线：每条独立绘制
			const polylines = props.mapData.polylines || []
			polylines.forEach((pl) => {
				if (pl.length >= 2) {
					_drawH5Polyline(pl, [])
				}
			})
		} else if (points.length > 0) {
			bmapInstance.centerAndZoom(new BMapGL.Point(points[0].lng, points[0].lat), props.mapData.zoom || 15)
		}
	}
	
	function _drawH5Polyline(polylinePoints, fallbackPoints) {
		// 构建原始坐标数组 [lng, lat]，供 LineLayer GeoJSON 使用
		let rawPath
		if (polylinePoints && polylinePoints.length >= 2) {
			rawPath = polylinePoints.map(p => [p[0], p[1]])
		} else if (fallbackPoints && fallbackPoints.length >= 2) {
			rawPath = fallbackPoints.map(p => [p.lng, p.lat])
		} else {
			return
		}

		// 优先使用 LineLayer（WebGL 纹理描边，支持箭头纹理 + 边框）
		if (window.BMapGL.LineLayer) {
			const lineData = {
				type: 'FeatureCollection',
				features: [{
					type: 'Feature',
					geometry: {
						type: 'LineString',
						coordinates: rawPath
					},
					properties: {
						name: 'route-main'
					}
				}]
			}

			lineLayer = new BMapGL.LineLayer({
				enablePicked: true,
				autoSelect: true,
				pickWidth: 30,
				pickHeight: 30,
				opacity: 1,
				selectedColor: '#0066ff',
				style: {
					sequence: false,
					marginLength: 8,
					borderColor: '#cc0000',
					borderMask: true,
					borderWeight: 2,
					strokeWeight: 8,
					strokeLineJoin: 'round',
					strokeLineCap: 'round',
					// 蓝色方向箭头纹理（竖向图片，自动沿路线横向平铺）
					strokeTextureUrl: '//mapopen-pub-jsapigl.bj.bcebos.com/svgmodel/Icon_road_blue_arrow.png',
					strokeTextureWidth: 16,
					strokeTextureHeight: 64,
				}
			})

			lineLayer.addEventListener('click', function(e) {
				if (e.value && e.value.dataIndex !== -1) {
					console.log('[Map] 路线被点击:', e.value)
				}
			})

			lineLayer.setData(lineData)
			bmapInstance.addNormalLayer(lineLayer)
		} else {
			// 降级方案：传统 Polyline（不支持 LineLayer 的旧版 API）
			console.log('[Map] LineLayer 不可用，降级使用 Polyline')
			const bmapPath = rawPath.map(p => new BMapGL.Point(p[0], p[1]))
			const polyline = new BMapGL.Polyline(bmapPath, {
				strokeColor: '#ff0000',
				strokeWeight: 5,
				strokeOpacity: 0.85,
				showDir: true,
				dirColor: '#0066ff',
				dirSize: 12
			})
			bmapInstance.addOverlay(polyline)
		}

		// 自适应视野
		const viewPath = rawPath.map(p => new BMapGL.Point(p[0], p[1]))
		bmapInstance.setViewport(viewPath)
	}

	onMounted(() => {
		if (props.mapData) initH5Map()
	})

	watch(() => props.mapData, (newVal) => {
		if (newVal && expanded.value) {
			if (bmapInstance) {
				updateH5Map()
			} else {
				initH5Map()
			}
		}
	})

	watch(expanded, (val) => {
		if (val) {
			// 展开时始终强制重建：v-if 销毁 DOM 后旧实例不可复用
			if (bmapInstance) {
				try { bmapInstance.destroy() } catch (e) { /* ignore */ }
				bmapInstance = null
				lineLayer = null
			}
			if (props.mapData) {
				nextTick(() => initH5Map())
			}
		} else {
			// 收起时销毁实例，释放 GPU 资源
			if (bmapInstance) {
				try { bmapInstance.destroy() } catch (e) { /* ignore */ }
				bmapInstance = null
				lineLayer = null
			}
		}
	})

	// 切换出行方式时，重新绘制路线
	watch(activeModeIndex, () => {
		if (bmapInstance && props.mapData && expanded.value) {
			updateH5Map()
		}
	})
	// #endif

	// mapData 变化时重置 mode tab 索引
	watch(() => props.mapData, () => {
		activeModeIndex.value = 0
	})

	// ============ 计算属性 ============
	const centerLng = computed(() => {
		if (props.mapData.center && props.mapData.center.length >= 1) return props.mapData.center[0]
		if (props.mapData.points && props.mapData.points.length > 0) return props.mapData.points[0].lng
		return 113.38
	})

	const centerLat = computed(() => {
		if (props.mapData.center && props.mapData.center.length >= 2) return props.mapData.center[1]
		if (props.mapData.points && props.mapData.points.length > 0) return props.mapData.points[0].lat
		return 22.52
	})

	// ============ 多模式路线计算属性 ============
	const modeRoutes = computed(() => {
		if (props.mapData.type === 'multi_mode_route') {
			return props.mapData.mode_routes || []
		}
		return []
	})

	const activeModeRoute = computed(() => {
		if (modeRoutes.value.length > 0) {
			const idx = Math.min(activeModeIndex.value, modeRoutes.value.length - 1)
			return modeRoutes.value[idx] || {}
		}
		// 兼容旧的 single route 类型
		if (props.mapData.type === 'route' && props.mapData.route) {
			return props.mapData.route
		}
		return {}
	})

	const activeModeIcon = computed(() => {
		const mode = activeModeRoute.value.mode || 'driving'
		const map = { walking: '🚶', transit: '🚌', driving: '🚗', riding: '🚲', bicycling: '🚲' }
		return map[mode] || '📍'
	})

	const activeModeLabel = computed(() => {
		const mode = activeModeRoute.value.mode || 'driving'
		const map = { walking: '步行', transit: '公交', driving: '驾车', riding: '骑行', bicycling: '骑行' }
		return map[mode] || mode
	})

	const headerIcon = computed(() => {
		if (props.mapData.type === 'route' || props.mapData.type === 'multi_route' || props.mapData.type === 'multi_mode_route') return '🛣'
		return '📍'
	})

	const headerTitle = computed(() => {
		if (props.mapData.type === 'route') {
			return `${modeText.value}路线规划`
		} else if (props.mapData.type === 'multi_mode_route') {
			const count = modeRoutes.value.length || 0
			return `${count} 种出行方式`
		} else if (props.mapData.type === 'multi_route') {
			const count = props.mapData.route_infos?.length || 0
			return `${count} 条路线规划`
		} else {
			return `找到 ${props.mapData.points ? props.mapData.points.length : 0} 个地点`
		}
	})

	const modeText = computed(() => {
		if (props.mapData.type === 'multi_route') {
			const modes = (props.mapData.route_infos || []).map(r => r.mode || 'driving')
			const map = { walking: '步行', transit: '公交', driving: '驾车', riding: '骑行', bicycling: '骑行' }
			const names = [...new Set(modes)].map(m => map[m] || m)
			return names.join('/')
		}
		const mode = props.mapData.route?.mode || 'driving'
		const map = { walking: '步行', transit: '公交', driving: '驾车', riding: '骑行', bicycling: '骑行' }
		return map[mode] || mode
	})

	const modeIcon = computed(() => {
		const mode = props.mapData.route?.mode || 'driving'
		const map = { walking: '🚶', transit: '🚌', driving: '🚗', riding: '🚲', bicycling: '🚲' }
		return map[mode] || '📍'
	})

	// ============ 地图 Markers ============
	const markers = computed(() => {
		if (!props.mapData.points) return []
		return props.mapData.points.map((point, index) => ({
			id: index,
			longitude: point.lng,
			latitude: point.lat,
			title: point.name,
			iconPath: getMarkerIcon(point.tag),
			width: 32,
			height: 32,
			callout: {
				content: point.name,
				color: '#333',
				fontSize: 12,
				borderRadius: 6,
				padding: 4,
				display: 'ALWAYS'
			}
		}))
	})

	// ============ 路线 Polyline ============
	const polyline = computed(() => {
		// 单条路线
		if (props.mapData.type === 'route' && props.mapData.points && props.mapData.points.length >= 2) {
			let points
			if (props.mapData.polyline_points && props.mapData.polyline_points.length >= 2) {
				points = props.mapData.polyline_points.map(p => ({
					longitude: p[0],
					latitude: p[1]
				}))
			} else {
				points = props.mapData.points.map(p => ({
					longitude: p.lng,
					latitude: p.lat
				}))
			}
			return [{
				points,
				color: '#007aff',
				width: 5,
				dottedLine: false,
				arrowLine: true
			}]
		}
		// 多模式路线：只绘制当前选中模式
		if (props.mapData.type === 'multi_mode_route' && activeModeRoute.value.polyline_points && activeModeRoute.value.polyline_points.length >= 2) {
			const points = activeModeRoute.value.polyline_points.map(p => ({
				longitude: p[0],
				latitude: p[1]
			}))
			return [{
				points,
				color: '#007aff',
				width: 5,
				dottedLine: false,
				arrowLine: true
			}]
		}
		// 多条路线：分别绘制
		if (props.mapData.type === 'multi_route' && props.mapData.polylines && props.mapData.polylines.length > 0) {
			const colors = ['#007aff', '#34c759', '#ff9500', '#ff3b30', '#5856d6']
			return props.mapData.polylines.map((pl, idx) => ({
				points: pl.map(p => ({ longitude: p[0], latitude: p[1] })),
				color: colors[idx % colors.length],
				width: 4,
				dottedLine: false,
				arrowLine: true
			}))
		}
		return []
	})

	function getMarkerIcon(tag) {
		if (!tag) return ''
		const map = {
			'起点': '/static/marker-start.png',
			'终点': '/static/marker-end.png',
			'我的收藏': '/static/marker-star.png',
			'地图推荐': '/static/marker-poi.png'
		}
		return map[tag] || ''
	}

	// ============ 标签映射 ============
	function getTagLabel(tag) {
		const map = {
			'我的收藏': '⭐ 收藏',
			'地图推荐': '📍 推荐',
			'起点': '起点',
			'终点': '终点'
		}
		return map[tag] || tag
	}

	function getTagClass(tag) {
		const map = {
			'我的收藏': 'star',
			'地图推荐': 'map',
			'起点': 'start',
			'终点': 'end'
		}
		return map[tag] || 'default'
	}

	// ============ 多路线图标 ============
	function multiRouteModeIcon(mode) {
		const map = { walking: '🚶', transit: '🚌', driving: '🚗', riding: '🚲', bicycling: '🚲' }
		return map[mode] || '📍'
	}

	// ============ 多模式 tabs 图标/标签 ============
	function modeTabIcon(mode) {
		const map = { walking: '🚶', transit: '🚌', driving: '🚗', riding: '🚲', bicycling: '🚲' }
		return map[mode] || '📍'
	}

	function modeTabLabel(mode) {
		const map = { walking: '步行', transit: '公交', driving: '驾车', riding: '骑行', bicycling: '骑行' }
		return map[mode] || mode
	}

	// ============ 交互 ============
	function centerOnPoint(point) {
		// 触发地图中心移动（小程序 map 组件通过属性控制）
		console.log('聚焦 POI:', point.name, point.lat, point.lng)
	}

	function onMarkerTap(e) {
		console.log('点击了标记点:', e)
	}

	function openSystemNav() {
		const startPoint = props.mapData.points?.find(p => p.tag === '起点')
		const endPoint = props.mapData.points?.find(p => p.tag === '终点') || props.mapData.points?.[props.mapData.points.length - 1]
		
		if (!endPoint) {
			uni.showToast({ title: '未找到目的地', icon: 'none' })
			return
		}
		
		// #ifdef H5
		// H5 模式：直接打开百度地图导航 URL
		if (startPoint) {
			const bdUrl = `https://map.baidu.com/dir/${startPoint.lng},${startPoint.lat}/${endPoint.lng},${endPoint.lat}/`
			window.open(bdUrl, '_blank')
		} else {
			// 没有起点时只打开位置
			const bdUrl = `https://map.baidu.com/geocoder?x=${endPoint.lng}&y=${endPoint.lat}&title=${encodeURIComponent(endPoint.name)}`
			window.open(bdUrl, '_blank')
		}
		// #endif
		
		// #ifndef H5
		// 小程序模式：使用 uni.openLocation
		uni.openLocation({
			latitude: endPoint.lat,
			longitude: endPoint.lng,
			name: endPoint.name,
			address: endPoint.address || '',
			success: () => {
				console.log('已打开系统地图导航')
			},
			fail: () => {
				uni.showToast({ title: '打开导航失败', icon: 'none' })
			}
		})
		// #endif
	}
</script>

<style lang="scss" scoped>
	.embedded-map {
		margin-top: 8px;
		border-radius: 12px;
		overflow: hidden;
		background-color: #fafafa;
		border: 1px solid #eee;
	}

	.map-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 10px 12px;
		cursor: pointer;

		&:active {
			background-color: #f5f5f5;
		}

		.map-header-left {
			display: flex;
			align-items: center;
			gap: 6px;
		}

		.map-header-icon { font-size: 16px; }
		.map-header-title { font-size: 13px; color: #444; font-weight: 500; }
		.map-header-arrow { font-size: 10px; color: #aaa; }
	}

	.map-body {
		.map-view {
			border-radius: 8px;
			margin: 0 8px;
			width: calc(100% - 16px);
		}
		.map-view-h5 {
			width: calc(100% - 16px);
			height: 400px;
			margin: 0 8px;
			border-radius: 8px;
			overflow: hidden;
		}
	}

	// ============ 路线信息卡片 ============
	.route-info-card {
		margin: 8px;
		padding: 10px 12px;
		background-color: #fff;
		border-radius: 10px;

		// ============ 出行方式切换 tabs ============
		.mode-tabs {
			display: flex;
			justify-content: center;
			gap: 4px;
			margin-bottom: 10px;
			padding-bottom: 10px;
			border-bottom: 1px solid #f0f0f0;
		}

		.mode-tab {
			display: flex;
			align-items: center;
			gap: 4px;
			padding: 6px 14px;
			border-radius: 16px;
			background-color: #f5f5f5;
			cursor: pointer;
			transition: all 0.2s;

			&:active {
				opacity: 0.8;
			}
		}

		.mode-tab-active {
			background-color: #007aff;
			.mode-tab-icon { font-size: 14px; }
			.mode-tab-label { color: #fff; font-size: 12px; font-weight: 500; }
		}

		.mode-tab-icon { font-size: 14px; }
		.mode-tab-label { font-size: 12px; color: #666; }

		.route-stats {
			display: flex;
			align-items: center;
			justify-content: center;
			gap: 12px;
			margin-bottom: 8px;
		}

		.route-stat-item {
			display: flex;
			align-items: center;
			gap: 4px;
		}

		.route-stat-icon { font-size: 16px; }
		.route-stat-label { font-size: 13px; color: #555; }
		.route-stat-value { font-size: 14px; font-weight: 600; color: #333; }
		.route-stat-divider { width: 1px; height: 14px; background-color: #ddd; }

		.route-separator {
			height: 1px;
			background-color: #eee;
			margin: 6px 0;
		}

		.multi-route-item {
			padding: 2px 0;
		}

		.route-steps {
			margin-top: 6px;
			padding-top: 6px;
			border-top: 1px solid #f0f0f0;
		}

		.step-item {
			display: flex;
			align-items: flex-start;
			gap: 6px;
			padding: 3px 0;
		}

		.step-num {
			width: 18px;
			height: 18px;
			border-radius: 50%;
			background-color: #007aff;
			color: #fff;
			font-size: 10px;
			text-align: center;
			line-height: 18px;
			flex-shrink: 0;
		}

		.step-text {
			font-size: 12px;
			color: #666;
			line-height: 1.5;
		}

		.nav-btn {
			margin-top: 10px;
			text-align: center;
			padding: 8px;
			background-color: #007aff;
			border-radius: 20px;

			&:active {
				opacity: 0.8;
			}

			text {
				font-size: 14px;
				color: #fff;
				font-weight: 500;
			}
		}
	}

	// ============ POI 列表 ============
	.poi-list {
		margin: 8px;
	}

	.poi-item {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 10px 12px;
		background-color: #fff;
		border-radius: 8px;
		margin-bottom: 6px;

		&:active {
			background-color: #f8f9fb;
		}

		.poi-item-left {
			display: flex;
			align-items: center;
			gap: 6px;
			flex: 1;
			overflow: hidden;
		}

		.poi-tag {
			font-size: 10px;
			padding: 2px 6px;
			border-radius: 4px;
			flex-shrink: 0;

			&.tag-star { background-color: #fff8e1; color: #f9a825; }
			&.tag-map { background-color: #e3f2fd; color: #1976d2; }
			&.tag-start { background-color: #e8f5e9; color: #388e3c; }
			&.tag-end { background-color: #fce4ec; color: #c62828; }
		}

		.poi-name {
			font-size: 13px;
			color: #333;
			overflow: hidden;
			text-overflow: ellipsis;
			white-space: nowrap;
		}

		.poi-item-right {
			display: flex;
			align-items: center;
			gap: 8px;
			flex-shrink: 0;
		}

		.poi-rating { font-size: 11px; color: #f9a825; }
		.poi-price { font-size: 11px; color: #999; }
	}
</style>
