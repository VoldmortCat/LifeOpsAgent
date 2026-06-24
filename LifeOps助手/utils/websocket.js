// WebSocket 客户端封装
// 连接后端 FastAPI WebSocket 服务: ws://host:port/chat/{thread_id}

const DEFAULT_HOST = 'localhost'
const DEFAULT_PORT = '8000'

/**
 * 创建 WebSocket 连接
 * @param {string} threadId - 对话线程 ID
 * @param {object} handlers - 事件处理器 { onOpen, onMessage, onClose, onError }
 * @returns {object} { send, close, reconnect }
 */
export function createWebSocket(threadId, handlers = {}) {
	const host = uni.getStorageSync('api_host') || DEFAULT_HOST
	const port = uni.getStorageSync('api_port') || DEFAULT_PORT
	const url = `ws://${host}:${port}/chat/${threadId}`

	let socket = null
	let reconnectTimer = null
	let reconnectAttempts = 0
	const maxReconnectAttempts = 5
	const reconnectBaseDelay = 1000

	function connect() {
		try {
			// H5 环境
			// #ifdef H5
			socket = new WebSocket(url)
			// #endif

			// 微信小程序环境
			// #ifdef MP-WEIXIN
			socket = wx.connectSocket({ url })
			// #endif

			// #ifdef H5
			socket.onopen = () => {
				reconnectAttempts = 0
				if (handlers.onOpen) handlers.onOpen()
			}

			socket.onmessage = (event) => {
				try {
					const data = JSON.parse(event.data)
					if (handlers.onMessage) handlers.onMessage(data)
				} catch (e) {
					console.warn('[WS] 消息解析失败:', e)
				}
			}

			socket.onclose = (event) => {
				if (handlers.onClose) handlers.onClose(event)
				tryReconnect()
			}

			socket.onerror = (error) => {
				if (handlers.onError) handlers.onError(error)
			}
			// #endif

			// #ifdef MP-WEIXIN
			wx.onSocketOpen(() => {
				reconnectAttempts = 0
				if (handlers.onOpen) handlers.onOpen()
			})

			wx.onSocketMessage((res) => {
				try {
					const data = JSON.parse(res.data)
					if (handlers.onMessage) handlers.onMessage(data)
				} catch (e) {
					console.warn('[WS] 消息解析失败:', e)
				}
			})

			wx.onSocketClose((event) => {
				if (handlers.onClose) handlers.onClose(event)
				tryReconnect()
			})

			wx.onSocketError((error) => {
				if (handlers.onError) handlers.onError(error)
			})
			// #endif
		} catch (e) {
			console.error('[WS] 连接失败:', e)
			tryReconnect()
		}
	}

	function tryReconnect() {
		if (reconnectAttempts >= maxReconnectAttempts) {
			console.log('[WS] 重连次数已达上限，停止重连')
			return
		}
		reconnectAttempts++
		const delay = reconnectBaseDelay * Math.pow(2, reconnectAttempts - 1)
		console.log(`[WS] ${delay}ms 后尝试第 ${reconnectAttempts} 次重连...`)
		reconnectTimer = setTimeout(connect, delay)
	}

	function send(data) {
		if (!socket) return
		// #ifdef H5
		if (socket.readyState === WebSocket.OPEN) {
			socket.send(data)
		}
		// #endif
		// #ifdef MP-WEIXIN
		wx.sendSocketMessage({ data })
		// #endif
	}

	function close() {
		if (reconnectTimer) clearTimeout(reconnectTimer)
		reconnectAttempts = maxReconnectAttempts // 阻止重连
		if (socket) {
			// #ifdef H5
			socket.close()
			// #endif
			// #ifdef MP-WEIXIN
			wx.closeSocket()
			// #endif
		}
	}

	function reconnect() {
		close()
		reconnectAttempts = 0
		connect()
	}

	connect()

	return { send, close, reconnect }
}
