<template>
	<view class="mine-page">
		<scroll-view class="mine-scroll" scroll-y>
			<!-- 用户卡片 -->
			<view class="user-card">
				<view class="avatar">
					<text class="avatar-text">🧑</text>
				</view>
				<text class="user-name">{{ userName }}</text>
				<text class="user-thread">当前线程: {{ chatStore.currentThreadId }}</text>
			</view>

			<!-- 知识库 -->
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
			</view>

			<!-- 设置 -->
			<view class="menu-section">
				<text class="menu-section-title">设置</text>

				<view class="menu-item" @click="handleServerConfig">
					<text class="menu-icon">⚙️</text>
					<text class="menu-label">服务器配置</text>
					<text class="menu-value">{{ serverHost }}</text>
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

				<view class="config-subtitle">出行配置</view>
				<view class="config-row">
					<text class="config-label">默认城市</text>
					<input class="config-input" v-model="mapsCity" placeholder="中山" />
				</view>

				<view class="config-subtitle">账单配置</view>
				<view class="config-row">
					<text class="config-label">表头跳过行</text>
					<input class="config-input config-input-short" v-model="billSkipRows" type="number" placeholder="17" />
				</view>

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

			<view class="bottom-spacer"></view>
		</scroll-view>
	</view>
</template>

<script setup>
	import { ref, onMounted } from 'vue'
	import { useChatStore } from '@/store/chat.js'
	import { getRagStatus, runRagTest, getUserConfig, saveUserConfig } from '@/utils/api.js'

	const chatStore = useChatStore()

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

	async function handleRagStatus() {
		try {
			const data = await getRagStatus()
			uni.showModal({ title: 'RAG 监控', content: JSON.stringify(data, null, 2), showCancel: false })
		} catch (e) {
			uni.showToast({ title: '获取失败，请确保后端已启动', icon: 'none' })
		}
	}

	async function handleRagTest() {
		try {
			uni.showLoading({ title: '运行评估中...' })
			const data = await runRagTest()
			uni.hideLoading()
			uni.showModal({ title: '评估报告', content: JSON.stringify(data, null, 2), showCancel: false })
		} catch (e) {
			uni.hideLoading()
			uni.showToast({ title: '测试失败，请确保后端已启动', icon: 'none' })
		}
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
			content: '基于 LangGraph 的多 Agent 智能生活管家\n\n后端: Python + LangGraph\n前端: uni-app (Vue3)\nLLM: 通义千问\n地图: 百度地图 API\n向量库: ChromaDB',
			showCancel: false
		})
	}

	// ============ 用户配置 ============

	function applyUserConfig(data) {
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
	.mine-page {
		height: 100%;
		background-color: #f5f6fa;
	}

	.mine-scroll {
		height: 100%;
		overflow-y: auto;
	}

	// 用户卡片
	.user-card {
		display: flex;
		flex-direction: column;
		align-items: center;
		padding: 28px 20px 20px;
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
	.user-name { font-size: 17px; font-weight: 600; color: #222; margin-bottom: 4px; }
	.user-thread { font-size: 11px; color: #bbb; font-family: monospace; }

	// 菜单组
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

		&:active { background-color: #f8f9fb; }
		&:last-child { border-bottom: none; }
	}

	.menu-icon { font-size: 18px; margin-right: 10px; }
	.menu-label { font-size: 14px; color: #333; flex: 1; }
	.menu-arrow { font-size: 16px; color: #ccc; }
	.menu-value { font-size: 12px; color: #aaa; }

	// 对话列表
	.thread-list { padding: 0 14px 8px; }

	.thread-item {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 8px 10px;
		border-radius: 8px;
		margin-bottom: 2px;

		&.active { background-color: #f0f7ff; }
		&:active { background-color: #f5f5f5; }
	}

	.thread-name { font-size: 13px; color: #555; }
	.thread-delete { font-size: 14px; opacity: 0.5; }
	.thread-empty { padding: 12px; text-align: center; }
	.thread-empty text { font-size: 12px; color: #ccc; }

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

	.bottom-spacer { height: 30px; }
</style>
