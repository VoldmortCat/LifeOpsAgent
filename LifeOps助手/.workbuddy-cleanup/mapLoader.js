// 百度地图 BMapGL 动态加载器
// 从后端 /api/config/map-ak 获取浏览器端 AK，动态注入脚本加载 BMapGL
// 解决：AK 存服务器环境变量，前端无需写死，更换 AK 只需改服务器配置

let loadPromise = null

/**
 * 加载 BMapGL（幂等：已加载则直接返回，加载中则复用同一 Promise）
 * @returns {Promise} 返回 window.BMapGL
 */
export function loadBMapGL() {
	if (typeof window === 'undefined') {
		return Promise.reject(new Error('非浏览器环境'))
	}
	if (window.BMapGL) {
		return Promise.resolve(window.BMapGL)
	}
	if (loadPromise) {
		return loadPromise
	}

	loadPromise = new Promise((resolve, reject) => {
		// 从后端获取 AK（相对路径，部署后走 nginx 同源代理）
		fetch('/api/config/map-ak')
			.then(r => r.json())
			.then(data => {
				const ak = data && data.ak
				if (!ak) throw new Error('未获取到百度地图 AK')

				const script = document.createElement('script')
				script.src = `https://api.map.baidu.com/api?type=webgl&v=1.0&ak=${ak}`
				script.onload = () => {
					// 脚本就绪后 BMapGL 可能还需初始化，轮询等待
					let tries = 0
					const timer = setInterval(() => {
						tries++
						if (window.BMapGL) {
							clearInterval(timer)
							resolve(window.BMapGL)
						} else if (tries > 100) {
							clearInterval(timer)
							reject(new Error('BMapGL 初始化超时'))
						}
					}, 100)
				}
				script.onerror = () => {
					loadPromise = null // 允许重试
					reject(new Error('BMapGL 脚本加载失败'))
				}
				document.head.appendChild(script)
			})
			.catch(err => {
				loadPromise = null
				reject(err)
			})
	})
	return loadPromise
}
