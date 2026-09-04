// REST API 封装
// 通用适配：默认同源（H5 部署走 nginx 反代、本地开发走 vite proxy），
// 也可在设置页用 api_host / api_port 覆盖（兼容微信小程序等跨域场景）
const DEFAULT_HOST = typeof window !== 'undefined' ? window.location.hostname : 'localhost'
const DEFAULT_PORT = typeof window !== 'undefined' ? (window.location.port || '80') : '8000'

function getBaseUrl() {
	const host = uni.getStorageSync('api_host') || DEFAULT_HOST
	const port = uni.getStorageSync('api_port') || DEFAULT_PORT
	// 80 端口省略端口号
	return port === '80' ? `http://${host}` : `http://${host}:${port}`
}

function getAuthHeader() {
	const token = uni.getStorageSync('auth_token')
	return token ? { 'Authorization': `Bearer ${token}` } : {}
}

function request(options) {
	return new Promise((resolve, reject) => {
		const baseUrl = getBaseUrl()
		const authHeader = getAuthHeader()
		uni.request({
			url: `${baseUrl}${options.url}`,
			method: options.method || 'GET',
			data: options.data || {},
			timeout: options.timeout || 15000,
			header: {
				'Content-Type': 'application/json',
				...authHeader,
				...(options.header || {})
			},
			success: (res) => {
				if (res.statusCode >= 200 && res.statusCode < 300) {
					resolve(res.data)
				} else if (res.statusCode === 401) {
					// Token expired or invalid
					uni.removeStorageSync('auth_token')
					uni.removeStorageSync('auth_user')
					uni.reLaunch({ url: '/pages/login/login' })
					reject(new Error('登录已过期，请重新登录'))
				} else {
					reject(new Error(`HTTP ${res.statusCode}: ${res.errMsg || '未知错误'}`))
				}
			},
			fail: (err) => {
				reject(new Error(`网络请求失败: ${err.errMsg || '请检查后端是否启动'}`))
			}
		})
	})
}

// ============ 认证 API ============

export function login(username, password) {
	return request({
		url: '/api/auth/login',
		method: 'POST',
		data: { username, password },
	})
}

export function register(username, password, displayName = '') {
	return request({
		url: '/api/auth/register',
		method: 'POST',
		data: { username, password, display_name: displayName },
	})
}

export function getMe() {
	return request({ url: '/api/auth/me' })
}

// ============ 账单 API ============

export function getBillSummary(period = 'month') {
	return request({ url: `/api/bills/summary?period=${period}`, timeout: 20000 })
}

export function getBillChartUrl(period, type) {
	const baseUrl = getBaseUrl()
	return `${baseUrl}/api/bills/chart-file?period=${period}&type=${type}`
}

// ============ 文档中心 API ============

export function getDocList() {
	return request({ url: '/api/docs/list' })
}

export function uploadDocument(filePath, category = 'other') {
	return new Promise((resolve, reject) => {
		const baseUrl = getBaseUrl()
		const authHeader = getAuthHeader()
		uni.uploadFile({
			url: `${baseUrl}/api/docs/import?category=${category}`,
			filePath: filePath,
			name: 'file',
			header: authHeader,
			success: (res) => {
				try {
					resolve(JSON.parse(res.data))
				} catch (e) {
					reject(new Error('解析响应失败'))
				}
			},
			fail: (err) => {
				reject(new Error(`上传失败: ${err.errMsg}`))
			}
		})
	})
}

export function getDocPreview(docPath) {
	return request({ url: `/api/docs/preview/${encodeURIComponent(docPath)}` })
}

// ============ RAG 监控 API ============

export function getRagStatus() {
	return request({ url: '/api/rag/status' })
}

export function runRagTest() {
	return request({ url: '/api/rag/test', method: 'POST' })
}

// ============ 对话管理 API ============

export function getConversations() {
	return request({ url: '/api/conversations' })
}

export function getConversation(threadId) {
	return request({ url: `/api/conversations/${threadId}` })
}

export function createConversation() {
	return request({ url: '/api/conversations', method: 'POST' })
}

export function deleteConversation(threadId) {
	return request({ url: `/api/conversations/${threadId}`, method: 'DELETE' })
}

export function updateConversation(threadId, title) {
	return request({
		url: `/api/conversations/${threadId}`,
		method: 'PUT',
		data: { title }
	})
}

// ============ 用户配置 API ============

export function getUserConfig() {
	return request({ url: '/api/user-config' })
}

export function saveUserConfig(config) {
	return request({
		url: '/api/user-config',
		method: 'POST',
		data: { config },
		timeout: 10000,
	})
}

export default {
	getBillSummary,
	getBillChartUrl,
	getDocList,
	uploadDocument,
	getDocPreview,
	getRagStatus,
	runRagTest,
	getConversations,
	getConversation,
	createConversation,
	deleteConversation,
	updateConversation,
	getUserConfig,
	saveUserConfig,
	login,
	register,
	getMe,
}
