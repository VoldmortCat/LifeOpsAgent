<template>
	<view class="personal-center">
		<!-- 头部 -->
		<view class="pc-header" :style="{ paddingTop: statusBarHeight + 10 + 'px' }">
			<view class="pc-header-row">
				<text class="pc-title">个人中心</text>
				<view class="pc-close" @click="$emit('close')">
					<text class="close-icon">✕</text>
				</view>
			</view>
		</view>

		<!-- 内容区域 -->
		<scroll-view class="pc-content" scroll-y>
			<!-- 用户头像信息 -->
			<view class="user-card">
				<view class="avatar">
					<text class="avatar-text">🧑</text>
				</view>
				<text class="user-name">{{ userName }}</text>
				<text class="user-thread">当前线程: {{ chatStore.currentThreadId }}</text>
			</view>

			<!-- 菜单列表 -->
			<view class="menu-section">
				<text class="menu-section-title">对话管理</text>

				<view class="menu-item" @click="handleNewChat">
					<text class="menu-icon">💬</text>
					<text class="menu-label">新建对话</text>
					<text class="menu-arrow">›</text>
				</view>

				<view class="menu-item" @click="showThreadList = !showThreadList">
					<text class="menu-icon">📋</text>
					<text class="menu-label">对话列表</text>
					<text class="menu-arrow">{{ showThreadList ? '⌄' : '›' }}</text>
				</view>

				<!-- 对话列表展开 -->
				<view v-if="showThreadList" class="thread-list">
					<view
						v-for="conv in chatStore.conversations"
						:key="conv.threadId"
						class="thread-item"
						:class="{ active: conv.threadId === chatStore.currentThreadId }"
						@click="switchThread(conv.threadId)"
					>
						<text class="thread-name">{{ conv.name }}</text>
						<text class="thread-delete" @click.stop="deleteThread(conv.threadId)">🗑</text>
					</view>
					<view v-if="chatStore.conversations.length === 0" class="thread-empty">
						<text>暂无对话记录</text>
					</view>
				</view>
			</view>

			<!-- RAG 监控 -->
			<view class="menu-section">
				<text class="menu-section-title">知识库管理</text>

				<view class="menu-item" @click="handleRagStatus">
					<text class="menu-icon">📊</text>
					<text class="menu-label">RAG 监控仪表盘</text>
					<text class="menu-arrow">›</text>
				</view>

				<view class="menu-item" @click="handleRagTest">
					<text class="menu-icon">🧪</text>
					<text class="menu-label">检索测试（5 条用例）</text>
					<text class="menu-arrow">›</text>
				</view>

				<view class="menu-item" @click="handleRagDetail">
					<text class="menu-icon">📝</text>
					<text class="menu-label">检索日志</text>
					<text class="menu-arrow">›</text>
				</view>
			</view>

			<!-- 设置 -->
			<view class="menu-section">
				<text class="menu-section-title">设置</text>

				<view class="menu-item" @click="handleServerConfig">
					<text class="menu-icon">⚙️</text>
					<text class="menu-label">服务器配置</text>
					<text class="menu-value">{{ serverHost }}</text>
				</view>

				<view class="menu-item" @click="handleModelConfig">
					<text class="menu-icon">🧠</text>
					<text class="menu-label">模型设置</text>
					<text class="menu-value">{{ currentModel }}</text>
				</view>

				<view class="menu-item" @click="handleClearCache">
					<text class="menu-icon">🗂</text>
					<text class="menu-label">清除缓存</text>
					<text class="menu-arrow">›</text>
				</view>
			</view>

			<!-- 用户配置 -->
			<view class="menu-section">
				<text class="menu-section-title">用户配置</text>

				<!-- 邮箱配置 -->
				<view class="config-subtitle">邮箱配置</view>
				<view class="config-row">
					<text class="config-label">邮箱账号</text>
					<input class="config-input" v-model="emailUsername" placeholder="请输入邮箱账号" />
				</view>
				<view class="config-row">
					<text class="config-label">邮箱密码</text>
					<input class="config-input" v-model="emailPassword" placeholder="请输入邮箱密码" :password="!showPassword" />
					<text class="config-eye" @click="showPassword = !showPassword">{{ showPassword ? '🙈' : '👁' }}</text>
				</view>
				<view class="config-row">
					<text class="config-label">IMAP 服务器</text>
					<input class="config-input" v-model="emailImap" placeholder="imap.163.com" />
				</view>
				<view class="config-row">
					<text class="config-label">监听文件夹</text>
					<input class="config-input" v-model="emailWatchFolder" placeholder="INBOX" />
				</view>

				<!-- 出行配置 -->
				<view class="config-subtitle">出行配置</view>
				<view class="config-row">
					<text class="config-label">默认城市</text>
					<input class="config-input" v-model="mapsCity" placeholder="中山" />
				</view>

				<!-- 账单配置 -->
				<view class="config-subtitle">账单配置</view>
				<view class="config-row">
					<text class="config-label">表头跳过行数</text>
					<input class="config-input config-input-short" v-model="billSkipRows" type="number" placeholder="17" />
				</view>

				<!-- 保存按钮 -->
				<view class="config-save-wrap">
					<view class="config-save-btn" :class="{ saving: isSaving }" @click="handleSaveConfig">
						<text>{{ isSaving ? '保存中...' : '保存配置' }}</text>
					</view>
				</view>
			</view>

			<!-- 关于 -->
			<view class="menu-section">
				<view class="menu-item" @click="handleAbout">
					<text class="menu-icon">ℹ️</text>
					<text class="menu-label">关于 LifeOps Agent</text>
					<text class="menu-value">V3.0</text>
				</view>
			</view>

			<!-- 底部留白 -->
			<view class="bottom-spacer"></view>
		</scroll-view>
	</view>
</template>

<script setup>
	import { ref, computed, onMounted } from 'vue'
	import { useChatStore } from '@/store/chat.js'
	import { getRagStatus, runRagTest, getUserConfig, saveUserConfig } from '@/utils/api.js'

	defineEmits(['close'])

	const chatStore = useChatStore()

	const statusBarHeight = ref(20)
	try {
		const info = uni.getSystemInfoSync()
		statusBarHeight.value = info.statusBarHeight || 20
	} catch (e) {}

	// ============ 状态 ============
	const showThreadList = ref(false)
	const userName = ref('LifeOps 用户')

	// ============ 用户配置状态 ============
	const emailUsername = ref('')
	const emailPassword = ref('******')
	const emailImap = ref('')
	const emailWatchFolder = ref('')
	const mapsCity = ref('')
	const billSkipRows = ref(17)
	const showPassword = ref(false)
	const isSaving = ref(false)

	// ============ 配置项（从本地存储读取） ============
	const serverHost = computed(() => {
		const host = uni.getStorageSync('api_host') || 'localhost'
		const port = uni.getStorageSync('api_port') || '8000'
		return `${host}:${port}`
	})

	const currentModel = computed(() => {
		return uni.getStorageSync('model_name') || 'qwen-max'
	})

	// ============ 对话管理 ============
	function switchThread(threadId) {
		chatStore.connect(threadId)
		showThreadList.value = false
	}

	function deleteThread(threadId) {
		uni.showModal({
			title: '删除对话',
			content: '确定要删除这个对话吗？',
			success: (res) => {
				if (res.confirm) {
					chatStore.deleteConversation(threadId)
				}
			}
		})
	}

	function handleNewChat() {
		uni.showModal({
			title: '新建对话',
			editable: true,
			placeholderText: '输入对话名称',
			success: (res) => {
				if (res.confirm && res.content) {
					chatStore.newConversation(res.content)
				} else if (res.confirm) {
					chatStore.newConversation()
				}
			}
		})
	}

	// ============ RAG 功能 ============
	async function handleRagStatus() {
		try {
			const data = await getRagStatus()
			uni.showModal({
				title: 'RAG 监控',
				content: JSON.stringify(data, null, 2),
				showCancel: false
			})
		} catch (e) {
			wx.showToast({ title: '获取失败，请确保后端已启动', icon: 'none' })
		}
	}

	async function handleRagTest() {
		try {
			uni.showLoading({ title: '运行评估中...' })
			const data = await runRagTest()
			uni.hideLoading()
			uni.showModal({
				title: '评估报告',
				content: JSON.stringify(data, null, 2),
				showCancel: false
			})
		} catch (e) {
			uni.hideLoading()
			wx.showToast({ title: '测试失败，请确保后端已启动', icon: 'none' })
		}
	}

	function handleRagDetail() {
		uni.showToast({ title: '检索日志功能开发中', icon: 'none' })
	}

	// ============ 设置 ============
	function handleServerConfig() {
		uni.showModal({
			title: '服务器配置',
			editable: true,
			placeholderText: '输入服务器地址',
			content: serverHost.value,
			success: (res) => {
				if (res.confirm && res.content) {
					const [host, port] = res.content.split(':')
					uni.setStorageSync('api_host', host || 'localhost')
					uni.setStorageSync('api_port', port || '8000')
					uni.showToast({ title: '配置已保存', icon: 'success' })
				}
			}
		})
	}

	function handleModelConfig() {
		uni.showActionSheet({
			itemList: ['qwen-max', 'qwen-plus', 'qwen-turbo'],
			success: (res) => {
				const models = ['qwen-max', 'qwen-plus', 'qwen-turbo']
				const selected = models[res.tapIndex]
				uni.setStorageSync('model_name', selected)
				uni.showToast({ title: `已切换至 ${selected}`, icon: 'success' })
			}
		})
	}

	function handleClearCache() {
		uni.showModal({
			title: '清除缓存',
			content: '将清除所有本地对话记录和设置，确定继续？',
			success: (res) => {
				if (res.confirm) {
					chatStore.conversations = []
					chatStore.clearMessages()
					uni.clearStorageSync()
					uni.showToast({ title: '缓存已清除', icon: 'success' })
				}
			}
		})
	}

	function handleAbout() {
		uni.showModal({
			title: 'LifeOps Agent V3.0',
			content: '基于 LangGraph 的多 Agent 智能生活管家\n\n技术栈：\n- 后端: Python + LangGraph\n- 前端: uni-app (Vue3)\n- LLM: 通义千问\n- 地图: 百度地图 API\n- 向量库: ChromaDB',
			showCancel: false
		})
	}

	// ============ 用户配置 ============

	function applyUserConfig(data) {
		// email 是嵌套对象，其余是扁平路径
		if (data.email && typeof data.email === 'object') {
			emailUsername.value = data.email.username || ''
			emailPassword.value = data.email.password || '******'
			emailImap.value = data.email.imap_server || ''
			emailWatchFolder.value = data.email.watch_folder || ''
		}
		if (data['maps.default_city'] !== undefined) {
			mapsCity.value = data['maps.default_city'] || ''
		}
		if (data['bill.skip_header_rows'] !== undefined) {
			billSkipRows.value = data['bill.skip_header_rows'] || 17
		}
	}

	async function fetchUserConfig() {
		try {
			const res = await getUserConfig()
			if (res && res.ok && res.config) {
				applyUserConfig(res.config)
			}
		} catch (e) {
			// 后端未启动时静默失败，使用默认值
		}
	}

	async function handleSaveConfig() {
		if (isSaving.value) return
		isSaving.value = true

		const payload = {
			email: {
				username: emailUsername.value,
				password: emailPassword.value,
				imap_server: emailImap.value,
				watch_folder: emailWatchFolder.value,
			},
			'maps.default_city': mapsCity.value,
			'bill.skip_header_rows': Number(billSkipRows.value) || 17,
		}

		try {
			const res = await saveUserConfig(payload)
			if (res && res.ok) {
				uni.showToast({ title: '配置已保存', icon: 'success' })
				// 刷新显示（后端脱敏后重新拉取）
				await fetchUserConfig()
			} else {
				uni.showToast({ title: res.error || '保存失败', icon: 'none' })
			}
		} catch (e) {
			uni.showToast({ title: '保存失败，请检查后端是否启动', icon: 'none' })
		} finally {
			isSaving.value = false
		}
	}

	onMounted(() => {
		fetchUserConfig()
	})
</script>

<style lang="scss" scoped>
	.personal-center {
		height: 100%;
		display: flex;
		flex-direction: column;
		background-color: #f8f9fb;
	}

	// ============ 头部 ============
	.pc-header {
		background-color: #fff;
		padding: 10px 16px 12px;
		border-bottom: 1px solid #eee;
	}

	.pc-header-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.pc-title {
		font-size: 18px;
		font-weight: 700;
		color: #222;
	}

	.pc-close {
		width: 30px;
		height: 30px;
		display: flex;
		align-items: center;
		justify-content: center;
		border-radius: 50%;

		&:active {
			background-color: #f0f0f0;
		}

		.close-icon {
			font-size: 16px;
			color: #999;
		}
	}

	// ============ 内容 ============
	.pc-content {
		flex: 1;
		overflow-y: auto;
	}

	// ============ 用户卡片 ============
	.user-card {
		display: flex;
		flex-direction: column;
		align-items: center;
		padding: 24px 20px 20px;
		background-color: #fff;
		margin: 12px;
		border-radius: 14px;
	}

	.avatar {
		width: 60px;
		height: 60px;
		border-radius: 50%;
		background-color: #f0f7ff;
		display: flex;
		align-items: center;
		justify-content: center;
		margin-bottom: 10px;
	}

	.avatar-text { font-size: 30px; }

	.user-name {
		font-size: 17px;
		font-weight: 600;
		color: #222;
		margin-bottom: 4px;
	}

	.user-thread {
		font-size: 11px;
		color: #bbb;
		font-family: monospace;
	}

	// ============ 菜单组 ============
	.menu-section {
		margin: 0 12px 12px;
		background-color: #fff;
		border-radius: 14px;
		overflow: hidden;
	}

	.menu-section-title {
		font-size: 12px;
		color: #aaa;
		padding: 12px 14px 4px;
		display: block;
	}

	.menu-item {
		display: flex;
		align-items: center;
		padding: 13px 14px;
		border-bottom: 1px solid #f8f8f8;

		&:active {
			background-color: #f8f9fb;
		}

		&:last-child {
			border-bottom: none;
		}
	}

	.menu-icon { font-size: 18px; margin-right: 10px; }
	.menu-label { font-size: 14px; color: #333; flex: 1; }
	.menu-arrow { font-size: 16px; color: #ccc; }
	.menu-value { font-size: 12px; color: #aaa; }

	// ============ 对话列表 ============
	.thread-list {
		padding: 0 14px 8px;
	}

	.thread-item {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 8px 10px;
		border-radius: 8px;
		margin-bottom: 2px;

		&.active {
			background-color: #f0f7ff;
		}

		&:active {
			background-color: #f5f5f5;
		}
	}

	.thread-name {
		font-size: 13px;
		color: #555;
	}

	.thread-delete {
		font-size: 14px;
		opacity: 0.5;

		&:active {
			opacity: 1;
		}
	}

	.thread-empty {
		padding: 12px;
		text-align: center;

		text {
			font-size: 12px;
			color: #ccc;
		}
	}

	// ============ 用户配置表单 ============
	.config-subtitle {
		font-size: 12px;
		color: #007aff;
		padding: 8px 14px 2px;
		display: block;
		font-weight: 600;
	}

	.config-row {
		display: flex;
		align-items: center;
		padding: 8px 14px;
	}

	.config-label {
		font-size: 13px;
		color: #666;
		width: 90px;
		flex-shrink: 0;
	}

	.config-input {
		flex: 1;
		height: 34px;
		border: 1px solid #e5e5e5;
		border-radius: 6px;
		padding: 0 10px;
		font-size: 13px;
		color: #333;
		background-color: #fafafa;

		&:focus {
			border-color: #007aff;
			background-color: #fff;
		}
	}

	.config-input-short {
		max-width: 100px;
	}

	.config-eye {
		font-size: 16px;
		padding: 0 6px;
		flex-shrink: 0;
	}

	.config-save-wrap {
		padding: 14px;
	}

	.config-save-btn {
		height: 44px;
		background-color: #007aff;
		border-radius: 10px;
		display: flex;
		align-items: center;
		justify-content: center;

		&:active {
			opacity: 0.8;
		}

		&.saving {
			background-color: #99c9ff;
		}

		text {
			font-size: 15px;
			color: #fff;
			font-weight: 600;
		}
	}

	// ============ 底部留白 ============
	.bottom-spacer {
		height: 30px;
	}
</style>
