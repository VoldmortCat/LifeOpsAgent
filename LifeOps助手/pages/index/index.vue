<template>
	<view class="main-container" :style="{ paddingTop: statusBarHeight + 'px' }">

		<!-- 左抽屉遮罩 -->
		<view
			v-if="showLeftDrawer"
			class="drawer-mask"
			@click="closeLeftDrawer"
			@touchmove.stop.prevent="() => {}"
		></view>

		<!-- 左抽屉：账单中心 -->
		<view
			class="drawer-panel drawer-left"
			:class="{ 'drawer-open': showLeftDrawer }"
			@touchmove.stop.prevent="() => {}"
		>
			<BillCenter @close="closeLeftDrawer" />
		</view>

		<!-- 头像弹窗遮罩 -->
		<view
			v-if="showUserPopup"
			class="popup-mask"
			@click="showUserPopup = false"
		></view>

		<!-- 头像弹出面板 -->
		<view v-if="showUserPopup" class="user-popup-panel">
			<view class="popup-section">
				<text class="popup-section-title">对话管理</text>
				<view class="popup-item" @click="handleNewChat">
					<text class="popup-icon">💬</text>
					<text>新建对话</text>
				</view>
				<view class="popup-item" @click="showThreadList = !showThreadList">
					<text class="popup-icon">📋</text>
					<text>对话列表</text>
				</view>
				<view v-if="showThreadList" class="popup-sub">
					<view
						v-for="conv in chatStore.conversations"
						:key="conv.threadId"
						class="popup-sub-item"
						:class="{ active: conv.threadId === chatStore.currentThreadId }"
						@click="switchThread(conv.threadId)"
					>
						<text class="popup-sub-name">{{ conv.name }}</text>
						<text class="popup-sub-del" @click.stop="deleteThread(conv.threadId)">🗑</text>
					</view>
					<text v-if="chatStore.conversations.length === 0" class="popup-sub-empty">暂无对话</text>
				</view>
			</view>

			<view class="popup-section">
				<text class="popup-section-title">设置</text>
				<view class="popup-item" @click="goToMinePage">
					<text class="popup-icon">👤</text>
					<text>个人中心</text>
				</view>
				<view class="popup-item" @click="handleModelConfig">
					<text class="popup-icon">🧠</text>
					<text>模型设置</text>
					<text class="popup-val">{{ currentModel }}</text>
				</view>
				<view class="popup-item" @click="handleAbout">
					<text class="popup-icon">ℹ️</text>
					<text>关于 LifeOps</text>
					<text class="popup-val">V3.0</text>
				</view>
			</view>
		</view>

		<!-- 顶部导航栏 -->
		<view class="navbar" :style="{ paddingTop: statusBarHeight + 'px' }">
			<view class="navbar-inner">
				<view class="navbar-left" @click="toggleLeftDrawer">
					<text class="nav-icon">📊</text>
					<text class="nav-label">账单</text>
				</view>
				<view class="navbar-center">
					<text class="nav-title">LifeOps Agent</text>
					<view class="connection-dot" :class="{ connected: chatStore.isConnected }"></view>
				</view>
				<view class="navbar-right" @click="showUserPopup = !showUserPopup">
					<view class="avatar-circle">
						<text class="avatar-text">🧑</text>
					</view>
				</view>
			</view>
		</view>

		<!-- 中间对话区域 -->
		<view class="chat-area">
			<scroll-view
				class="message-list"
				scroll-y
				:scroll-into-view="scrollToId"
				:scroll-with-animation="true"
			>
				<view v-if="chatStore.messages.length === 0" class="empty-state">
					<image class="empty-logo" src="/static/logo.png" mode="aspectFit"></image>
					<text class="empty-title">LifeOps Agent</text>
					<text class="empty-desc">智能生活管家，随时为您服务</text>
					<view class="quick-actions">
						<view class="quick-btn" @click="quickSend('本月账单汇总')">
							<text>💳 本月账单</text>
						</view>
						<view class="quick-btn" @click="quickSend('推荐附近好吃的乳鸽店')">
							<text>🍗 附近美食</text>
						</view>
						<view class="quick-btn" @click="quickSend('今天天气怎么样')">
							<text>🌤 今日天气</text>
						</view>
						<view class="quick-btn" @click="quickSend('中山有哪些值得去的景点')">
							<text>🗺 景点推荐</text>
						</view>
					</view>
				</view>

				<view
					v-for="(msg, idx) in chatStore.messages"
					:key="msg.id"
					:id="'msg-' + idx"
				>
					<MessageBubble
						:message="msg"
						:is-last="idx === chatStore.messages.length - 1"
					/>
				</view>

				<view v-if="chatStore.isStreaming" class="streaming-indicator">
					<view class="typing-dot"></view>
					<view class="typing-dot"></view>
					<view class="typing-dot"></view>
				</view>

				<view class="bottom-spacer"></view>
			</scroll-view>

			<InputBar @send="handleSend" />
		</view>

	</view>
</template>

<script setup>
	import { ref, watch, nextTick, onMounted, computed } from 'vue'
	import { useChatStore } from '@/store/chat.js'
	import MessageBubble from '@/components/MessageBubble.vue'
	import InputBar from '@/components/InputBar.vue'
	import BillCenter from '@/components/BillCenter.vue'

	const chatStore = useChatStore()

	const showLeftDrawer = ref(false)
	const showUserPopup = ref(false)
	const showThreadList = ref(false)
	const scrollToId = ref('')
	const statusBarHeight = ref(0)

	const serverHost = computed(() => {
		const host = uni.getStorageSync('api_host') || 'localhost'
		const port = uni.getStorageSync('api_port') || '8000'
		return `${host}:${port}`
	})

	const currentModel = computed(() => {
		return uni.getStorageSync('model_name') || 'qwen-max'
	})

	onMounted(() => {
		const si = uni.getSystemInfoSync()
		statusBarHeight.value = si.statusBarHeight || 20
		chatStore.screenWidth = si.screenWidth
		chatStore.screenHeight = si.screenHeight
		chatStore.connect('default')
	})

	function toggleLeftDrawer() {
		showLeftDrawer.value = !showLeftDrawer.value
		showUserPopup.value = false
	}

	function closeLeftDrawer() {
		showLeftDrawer.value = false
	}

	function handleSend(content) {
		closeLeftDrawer()
		showUserPopup.value = false
		chatStore.sendMessage(content)
		scrollToBottom()
	}

	function quickSend(content) {
		handleSend(content)
	}

	function scrollToBottom() {
		nextTick(() => {
			const idx = chatStore.messages.length - 1
			scrollToId.value = idx >= 0 ? 'msg-' + idx : ''
		})
	}

	watch(() => chatStore.messages.length, () => {
		scrollToBottom()
	})

	function switchThread(threadId) {
		chatStore.connect(threadId)
		showThreadList.value = false
		showUserPopup.value = false
	}

	function deleteThread(threadId) {
		uni.showModal({
			title: '删除对话',
			content: '确定要删除这个对话吗？',
			success: (res) => {
				if (res.confirm) chatStore.deleteConversation(threadId)
			}
		})
	}

	function goToMinePage() {
		showUserPopup.value = false
		uni.navigateTo({ url: '/pages/mine/mine' })
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
				showUserPopup.value = false
			}
		})
	}

	function handleServerConfig() {
		uni.showModal({
			title: '服务器配置',
			editable: true,
			placeholderText: '输入地址，如 192.168.1.5:8000',
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
				uni.setStorageSync('model_name', models[res.tapIndex])
				uni.showToast({ title: `已切换至 ${models[res.tapIndex]}`, icon: 'success' })
			}
		})
	}

	function handleAbout() {
		uni.showModal({
			title: 'LifeOps Agent V3.0',
			content: '基于 LangGraph 的多 Agent 智能生活管家\n\n后端: Python + LangGraph\n前端: uni-app (Vue3)\nLLM: 通义千问\n地图: 百度地图 API\n向量库: ChromaDB',
			showCancel: false
		})
	}

	// 全局手势：左边缘右滑打开账单抽屉
	let touchStartX = 0; let touchStartY = 0
	onMounted(() => {
		// #ifdef H5
		document.addEventListener('touchstart', (e) => {
			touchStartX = e.touches[0].clientX
			touchStartY = e.touches[0].clientY
		}, { passive: true })
		document.addEventListener('touchend', (e) => {
			const dx = e.changedTouches[0].clientX - touchStartX
			const dy = e.changedTouches[0].clientY - touchStartY
			if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) {
				if (dx > 0 && touchStartX < 40) {
					showLeftDrawer.value = true
				}
			}
		}, { passive: true })
		// #endif
	})
</script>

<style lang="scss" scoped>
	.main-container {
		height: 100vh;
		height: calc(100vh - env(safe-area-inset-bottom, 0px) - 50px);
		display: flex;
		flex-direction: column;
		background-color: #f5f6fa;
		overflow: hidden;
		position: relative;
	}

	.drawer-mask, .popup-mask {
		position: fixed;
		top: 0;
		left: 0;
		right: 0;
		bottom: 0;
		background-color: rgba(0, 0, 0, 0.45);
		z-index: 100;
	}

	.popup-mask { z-index: 150; }

	.drawer-panel {
		position: fixed;
		top: 0;
		bottom: 0;
		width: 82vw;
		background-color: #fff;
		z-index: 200;
		transition: transform 0.3s cubic-bezier(0.25, 0.46, 0.45, 0.94);
		box-shadow: 0 0 30px rgba(0, 0, 0, 0.1);

		&.drawer-left {
			left: 0;
			transform: translateX(-100%);
		}

		&.drawer-open {
			transform: translateX(0);
		}
	}

	// 头像弹窗
	.user-popup-panel {
		position: fixed;
		top: 60px;
		right: 12px;
		width: 260px;
		background-color: #fff;
		border-radius: 14px;
		box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
		z-index: 300;
		overflow: hidden;
		animation: popIn 0.2s ease;
	}

	@keyframes popIn {
		from { opacity: 0; transform: translateY(-8px) scale(0.95); }
		to { opacity: 1; transform: translateY(0) scale(1); }
	}

	.popup-section {
		padding: 8px 0;
		border-bottom: 1px solid #f0f0f0;

		&:last-child { border-bottom: none; }
	}

	.popup-section-title {
		font-size: 11px;
		color: #aaa;
		padding: 4px 16px 6px;
		display: block;
	}

	.popup-item {
		display: flex;
		align-items: center;
		padding: 10px 16px;
		gap: 8px;
		font-size: 14px;
		color: #333;

		&:active { background-color: #f8f9fb; }

		.popup-icon { font-size: 16px; }
		.popup-val { font-size: 11px; color: #bbb; margin-left: auto; }
	}

	.popup-sub {
		padding: 0 12px 4px;
	}

	.popup-sub-item {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 6px 10px;
		border-radius: 6px;
		font-size: 12px;
		color: #666;

		&.active { background-color: #f0f7ff; }
		&:active { background-color: #f5f5f5; }
	}

	.popup-sub-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.popup-sub-del { font-size: 14px; opacity: 0.5; padding-left: 8px; }
	.popup-sub-empty { font-size: 11px; color: #ccc; text-align: center; padding: 8px; }

	// 导航栏
	.navbar {
		background-color: #fff;
		border-bottom: 1px solid #eee;
		z-index: 10;

		.navbar-inner {
			height: 44px;
			display: flex;
			align-items: center;
			justify-content: space-between;
			padding: 0 16px;
		}

		.navbar-left {
			display: flex;
			align-items: center;
			gap: 4px;
			padding: 4px 8px;
			border-radius: 8px;

			&:active { background-color: #f0f0f0; }
		}

		.nav-icon { font-size: 20px; }
		.nav-label { font-size: 14px; color: #333; font-weight: 500; }

		.navbar-center {
			display: flex;
			align-items: center;
			gap: 8px;
		}

		.nav-title { font-size: 17px; font-weight: 600; color: #222; }

		.connection-dot {
			width: 8px;
			height: 8px;
			border-radius: 50%;
			background-color: #ccc;

			&.connected { background-color: #4cd964; }
		}

		.navbar-right {
			padding: 2px;
			border-radius: 50%;
		}
	}

	.avatar-circle {
		width: 32px;
		height: 32px;
		border-radius: 50%;
		background-color: #f0f7ff;
		display: flex;
		align-items: center;
		justify-content: center;
		border: 2px solid #e0edff;

		.avatar-text { font-size: 18px; }
	}

	// 对话区域
	.chat-area {
		flex: 1;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.message-list {
		flex: 1;
		padding: 12px 16px;
		overflow-y: auto;
	}

	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		padding-top: 60px;
	}

	.empty-logo { width: 80px; height: 80px; border-radius: 20px; margin-bottom: 16px; }
	.empty-title { font-size: 22px; font-weight: 700; color: #222; margin-bottom: 6px; }
	.empty-desc { font-size: 14px; color: #999; margin-bottom: 32px; }

	.quick-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		justify-content: center;
		padding: 0 20px;
	}

	.quick-btn {
		padding: 10px 16px;
		background-color: #fff;
		border-radius: 20px;
		border: 1px solid #e0e0e0;
		font-size: 13px;
		color: #333;
		box-shadow: 0 1px 3px rgba(0,0,0,0.04);

		&:active { background-color: #f5f5f5; }
	}

	.streaming-indicator {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 12px 16px;

		.typing-dot {
			width: 7px;
			height: 7px;
			border-radius: 50%;
			background-color: #bbb;
			animation: typingBounce 1.4s ease-in-out infinite;

			&:nth-child(2) { animation-delay: 0.2s; }
			&:nth-child(3) { animation-delay: 0.4s; }
		}
	}

	@keyframes typingBounce {
		0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
		30% { transform: translateY(-6px); opacity: 1; }
	}

	.bottom-spacer { height: 16px; }
</style>
