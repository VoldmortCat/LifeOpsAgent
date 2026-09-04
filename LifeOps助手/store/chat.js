import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { createWebSocket } from '@/utils/websocket.js'
import { getConversations, getConversation, createConversation, deleteConversation as apiDeleteConversation } from '@/utils/api.js'

export const useChatStore = defineStore('chat', () => {
	// ============ 对话状态 ============
	const conversations = ref([])
	const currentThreadId = ref('')
	const messages = ref([])
	const isConnected = ref(false)
	const isStreaming = ref(false)
	const wsClient = ref(null)
	const isLoading = ref(false)

	// ============ 设备信息 ============
	const screenWidth = ref(375)
	const screenHeight = ref(667)

	// ============ 计算属性 ============
	const currentConversation = computed(() => {
		return conversations.value.find(c => c.thread_id === currentThreadId.value)
	})

	const lastAgentMessage = computed(() => {
		const agentMsgs = messages.value.filter(m => m.role === 'agent')
		return agentMsgs.length > 0 ? agentMsgs[agentMsgs.length - 1] : null
	})

	// ============ 初始化 ============
	async function init() {
		isLoading.value = true
		try {
			const res = await getConversations()
			if (res && res.conversations) {
				conversations.value = res.conversations
				// 自动选择最新的对话
				if (conversations.value.length > 0) {
					const latest = conversations.value[0]
					currentThreadId.value = latest.thread_id
					await loadMessages(latest.thread_id)
				} else {
					// 无对话，创建新对话
					await createNewConversation()
				}
			}
		} catch (e) {
			console.error('加载对话列表失败:', e)
			// 创建默认对话
			if (!currentThreadId.value) {
				createNewConversation()
			}
		} finally {
			isLoading.value = false
		}
		// 连接 WebSocket
		if (currentThreadId.value) {
			connect(currentThreadId.value)
		}
	}

	async function loadMessages(threadId) {
		try {
			const res = await getConversation(threadId)
			if (res && res.ok && res.messages) {
				// 转换后端消息格式为前端格式
				messages.value = res.messages.map(m => ({
					id: `msg_${m.id}`,
					role: m.role,
					content: m.content,
					timestamp: new Date(m.created_at).getTime(),
					msg_type: m.msg_type,
				}))
			} else {
				messages.value = []
			}
		} catch (e) {
			console.error('加载消息失败:', e)
			messages.value = []
		}
	}

	async function createNewConversation(name = '新对话') {
		try {
			const res = await createConversation()
			if (res && res.ok && res.conversation) {
				conversations.value.unshift(res.conversation)
				currentThreadId.value = res.conversation.thread_id
				messages.value = []
				connect(res.conversation.thread_id)
			}
		} catch (e) {
			// 离线回退：创建本地对话
			const threadId = `thread_local_${Date.now()}`
			conversations.value.unshift({
				thread_id: threadId,
				title: name,
				msg_count: 0,
				created_at: new Date().toISOString(),
			})
			currentThreadId.value = threadId
			messages.value = []
			connect(threadId)
		}
	}

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
			timestamp: Date.now()
		})

		streamBuffer.value = []
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
			return `**LifeOps Agent 帮助**

| 命令 | 功能 |
|------|------|
| /help | 查看帮助 |
| /rag | RAG 监控仪表盘 |
| /rag_test | 运行 RAG 批量评估 |
| quit / exit / q | 退出 |`
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
			return '📊 RAG 监控仪表盘

正在加载监控数据...

> 提示：请前往「个人中心 → RAG 监控」查看完整仪表盘'
		}
		if (trimmed === '/rag_test') {
			return '🧪 RAG 批量评估

正在运行 5 条测试用例...

> 提示：请前往「个人中心 → RAG 监控 → 检索测试」运行完整评估'
		}

		return null
	}

	// ============ 对话管理 ============
	function clearMessages() {
		messages.value = []
		streamBuffer.value = []
	}

	async function newConversation(name) {
		await createNewConversation(name || '新对话')
	}

	async function switchConversation(threadId) {
		if (threadId === currentThreadId.value) return
		currentThreadId.value = threadId
		clearMessages()
		await loadMessages(threadId)
		connect(threadId)
	}

	async function deleteConversation(threadId) {
		// 本地删除
		conversations.value = conversations.value.filter(c => c.thread_id !== threadId)

		// 后端删除
		try {
			await apiDeleteConversation(threadId)
		} catch (e) {
			console.error('删除对话失败:', e)
		}

		// 如果删除的是当前对话，切换到下一个
		if (currentThreadId.value === threadId) {
			const first = conversations.value[0]
			if (first) {
				await switchConversation(first.thread_id)
			} else {
				await createNewConversation('新对话')
			}
		}
	}

	async function refreshConversations() {
		try {
			const res = await getConversations()
			if (res && res.conversations) {
				conversations.value = res.conversations
			}
		} catch (e) {
			console.error('刷新对话列表失败:', e)
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
		isLoading,
		screenWidth,
		screenHeight,
		lastAgentMessage,
		init,
		connect,
		disconnect,
		sendMessage,
		clearMessages,
		newConversation,
		switchConversation,
		deleteConversation,
		refreshConversations,
	}
})
