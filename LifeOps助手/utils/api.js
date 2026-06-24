// REST API 封装
const DEFAULT_HOST = 'localhost'
const DEFAULT_PORT = '8000'

function getBaseUrl() {
	const host = uni.getStorageSync('api_host') || DEFAULT_HOST
	const port = uni.getStorageSync('api_port') || DEFAULT_PORT
	return `http://${host}:${port}`
}

function request(options) {
	return new Promise((resolve, reject) => {
		const baseUrl = getBaseUrl()
		uni.request({
			url: `${baseUrl}${options.url}`,
			method: options.method || 'GET',
			data: options.data || {},
			timeout: options.timeout || 15000,
			header: {
				'Content-Type': 'application/json',
				...(options.header || {})
			},
			success: (res) => {
				if (res.statusCode >= 200 && res.statusCode < 300) {
					resolve(res.data)
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
		uni.uploadFile({
			url: `${baseUrl}/api/docs/import?category=${category}`,
			filePath: filePath,
			name: 'file',
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

export function deleteConversation(threadId) {
	return request({ url: `/api/conversations/${threadId}`, method: 'DELETE' })
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
	deleteConversation,
	getUserConfig,
	saveUserConfig,
}
