import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { createWebSocket } from '@/utils/websocket.js'

export const useChatStore = defineStore('chat', () => {
	// ============ 对话状态 ============
	const conversations = ref([])
	const currentThreadId = ref('default')
	const messages = ref([])
	const isConnected = ref(false)
	const isStreaming = ref(false)
	const wsClient = ref(null)

	// ============ 设备信息 ============
	const screenWidth = ref(375)
	const screenHeight = ref(667)

	// ============ 计算属性 ============
	const currentConversation = computed(() => {
		return conversations.value.find(c => c.threadId === currentThreadId.value)
	})

	const lastAgentMessage = computed(() => {
		const agentMsgs = messages.value.filter(m => m.role === 'agent')
		return agentMsgs.length > 0 ? agentMsgs[agentMsgs.length - 1] : null
	})

	// ============ WebSocket 连接 ============
	function connect(threadId) {
		if (threadId) currentThreadId.value = threadId

		if (wsClient.value) {
			wsClient.value.close()
		}

		wsClient.value = createWebSocket(currentThreadId.value, {
			onOpen: () => {
				isConnected.value = true
				console.log('[WS] 已连接 thread=', currentThreadId.value)
			},
			onMessage: (data) => {
				handleStreamMessage(data)
			},
			onClose: () => {
				isConnected.value = false
				console.log('[WS] 已断开')
			},
			onError: (err) => {
				console.error('[WS] 错误:', err)
			}
		})
	}

	function disconnect() {
		if (wsClient.value) {
			wsClient.value.close()
			wsClient.value = null
		}
		isConnected.value = false
	}

	// ============ 流式消息处理 ============
	function handleStreamMessage(data) {
		const { type, content, tool_name, tool_status } = data

		switch (type) {
			case 'map_data':
				pendingMapData.value = data.data
				break

			case 'thinking':
				// Agent 开始思考
				isStreaming.value = true
				appendOrUpdateStream({ type: 'thinking', content })
				break

			case 'tool_start':
				// 工具调用开始
				appendOrUpdateStream({
					type: 'tool_call',
					toolName: tool_name,
					status: 'running',
					content: `正在调用 ${tool_name}...`
				})
				break

			case 'tool_end':
				// 工具调用结束
				updateLastStreamOfType('tool_call', {
					status: 'done',
					content: tool_status || `✅ ${tool_name} 执行完成`
				})
				break

			case 'text':
				// 最终回答文本（流式追加）
				isStreaming.value = true
				appendOrUpdateStream({ type: 'text', content })
				break

			case 'done':
				// 流式输出结束，合并成最终消息
				commitStreamMessage()
				isStreaming.value = false
				break

			case 'error':
				messages.value.push({
					id: genId(),
					role: 'agent',
					content: `❌ 出错了: ${content}`,
					timestamp: Date.now()
				})
				isStreaming.value = false
				break
		}
	}

	// 流式输出缓冲区
	const streamBuffer = ref([])
	const pendingMapData = ref(null)

	function appendOrUpdateStream(item) {
		streamBuffer.value.push(item)
	}

	function updateLastStreamOfType(type, updates) {
		const reversed = [...streamBuffer.value].reverse()
		const idx = reversed.findIndex(item => item.type === type)
		if (idx !== -1) {
			const realIdx = streamBuffer.value.length - 1 - idx
			Object.assign(streamBuffer.value[realIdx], updates)
		}
	}

	function commitStreamMessage() {
		if (streamBuffer.value.length === 0) return

		const thinkingParts = streamBuffer.value.filter(i => i.type === 'thinking')
		const toolParts = streamBuffer.value.filter(i => i.type === 'tool_call')
		const textParts = streamBuffer.value.filter(i => i.type === 'text')

		const fullContent = textParts.map(t => t.content).join('')
		const thinkingContent = thinkingParts.map(t => t.content).join('')
		const toolsUsed = toolParts.map(t => ({ name: t.toolName, status: t.status }))

		messages.value.push({
			id: genId(),
			role: 'agent',
			content: fullContent,
			thinking: thinkingContent || null,
			toolsUsed: toolsUsed.length > 0 ? toolsUsed : null,
			mapData: pendingMapData.value,
			timestamp: Date.now()
		})

		streamBuffer.value = []
		pendingMapData.value = null
	}

	// ============ 发送消息 ============
	function sendMessage(content) {
		if (!content.trim()) return
		if (!wsClient.value || !isConnected.value) {
			connect(currentThreadId.value)
		}

		// 处理内置命令（本地解析）
		const cmdResult = parseLocalCommand(content)
		if (cmdResult) {
			messages.value.push({
				id: genId(),
				role: 'user',
				content,
				timestamp: Date.now()
			})
			messages.value.push({
				id: genId(),
				role: 'agent',
				content: cmdResult,
				timestamp: Date.now()
			})
			return
		}

		// 添加用户消息
		messages.value.push({
			id: genId(),
			role: 'user',
			content,
			timestamp: Date.now()
		})

		// 发送到后端
		wsClient.value.send(JSON.stringify({
			type: 'message',
			content: content,
			thread_id: currentThreadId.value
		}))
	}

	// ============ 本地命令解析 ============
	function parseLocalCommand(content) {
		const trimmed = content.trim()

		if (trimmed === '/help') {
			return `**LifeOps Agent 帮助**\n\n| 命令 | 功能 |\n|------|------|\n| /help | 查看帮助 |\n| /rag | RAG 监控仪表盘 |\n| /rag_test | 运行 RAG 批量评估 |\n| 切换用户 <名> | 切换 thread_id |\n| quit / exit / q | 退出 |`
		}
		if (trimmed === 'quit' || trimmed === 'exit' || trimmed === 'q') {
			return '再见！如需重新开始对话，请刷新页面。'
		}
		if (trimmed.startsWith('切换用户')) {
			const name = trimmed.replace('切换用户', '').trim()
			if (name) {
				currentThreadId.value = name
				connect(name)
				return `已切换到用户「${name}」，thread_id=${name}`
			}
			return '请指定用户名，例如：切换用户 张三'
		}
		if (trimmed === '/rag') {
			return '📊 RAG 监控仪表盘\n\n正在加载监控数据...\n\n> 提示：请前往「个人中心 → RAG 监控」查看完整仪表盘'
		}
		if (trimmed === '/rag_test') {
			return '🧪 RAG 批量评估\n\n正在运行 5 条测试用例...\n\n> 提示：请前往「个人中心 → RAG 监控 → 检索测试」运行完整评估'
		}

		return null
	}

	// ============ 消息管理 ============
	function clearMessages() {
		messages.value = []
		streamBuffer.value = []
	}

	function newConversation(name) {
		const threadId = `thread_${Date.now()}`
		conversations.value.unshift({
			threadId,
			name: name || `对话 ${conversations.value.length + 1}`,
			createdAt: Date.now(),
			lastMessage: ''
		})
		currentThreadId.value = threadId
		clearMessages()
		connect(threadId)
	}

	function deleteConversation(threadId) {
		conversations.value = conversations.value.filter(c => c.threadId !== threadId)
		if (currentThreadId.value === threadId) {
			const first = conversations.value[0]
			if (first) {
				currentThreadId.value = first.threadId
				connect(first.threadId)
			} else {
				newConversation('新对话')
			}
		}
	}

	// ============ 工具函数 ============
	let idCounter = 0
	function genId() {
		return `msg_${Date.now()}_${idCounter++}`
	}

	return {
		conversations,
		currentThreadId,
		messages,
		isConnected,
		isStreaming,
		screenWidth,
		screenHeight,
		lastAgentMessage,
		connect,
		disconnect,
		sendMessage,
		clearMessages,
		newConversation,
		deleteConversation
	}
})
