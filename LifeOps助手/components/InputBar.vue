<template>
	<view class="input-bar" :style="{ paddingBottom: safeAreaBottom + 'px' }">
		<!-- 快捷命令提示 -->
		<view v-if="showCommands" class="command-hints">
			<view
				v-for="cmd in filteredCommands"
				:key="cmd.trigger"
				class="command-item"
				@click="selectCommand(cmd.trigger)"
			>
				<text class="cmd-trigger">{{ cmd.trigger }}</text>
				<text class="cmd-desc">{{ cmd.description }}</text>
			</view>
		</view>

		<!-- 输入区域 -->
		<view class="input-row">
			<!-- 语音按钮 -->
			<view class="input-btn" @click="handleVoice">
				<text class="btn-icon">🎤</text>
			</view>

			<!-- 输入框 -->
			<view class="input-wrapper">
				<input
					class="input-field"
					v-model="inputText"
					type="text"
					placeholder="输入消息或输入 / 查看命令..."
					:adjust-position="false"
					confirm-type="send"
					@confirm="handleSend"
					@input="onInput"
					@focus="onFocus"
					@blur="onBlur"
				/>
			</view>

			<!-- 发送按钮 -->
			<view
				v-if="inputText.trim()"
				class="send-btn"
				@click="handleSend"
			>
				<text class="send-icon">➤</text>
			</view>

			<!-- 更多按钮（输入为空时） -->
			<view v-else class="input-btn" @click="handleMore">
				<text class="btn-icon">＋</text>
			</view>
		</view>
	</view>
</template>

<script setup>
	import { ref, computed } from 'vue'

	const emit = defineEmits(['send'])

	const inputText = ref('')
	const showCommands = ref(false)
	const safeAreaBottom = ref(0)

	// 获取安全区高度
	try {
		const systemInfo = uni.getSystemInfoSync()
		safeAreaBottom.value = systemInfo.safeAreaInsets ? systemInfo.safeAreaInsets.bottom : 0
	} catch (e) {
		safeAreaBottom.value = 0
	}

	// ============ 命令列表（与 CLI 保持一致） ============
	const commands = [
		{ trigger: '/help', description: '查看帮助' },
		{ trigger: '/rag', description: 'RAG 监控仪表盘' },
		{ trigger: '/rag_test', description: '运行 RAG 批量评估' },
		{ trigger: '切换用户 ', description: '切换对话线程' },
		{ trigger: 'quit', description: '退出会话' }
	]

	const filteredCommands = computed(() => {
		const val = inputText.value.trim().toLowerCase()
		if (!val) return commands
		return commands.filter(c => c.trigger.toLowerCase().includes(val))
	})

	// ============ 输入处理 ============
	function onInput(e) {
		const val = e.detail.value || e.target.value || ''
		if (val.startsWith('/')) {
			showCommands.value = true
		} else {
			showCommands.value = false
		}
	}

	function onFocus() {
		if (inputText.value.startsWith('/') || inputText.value.trim() === '') {
			showCommands.value = true
		}
	}

	function onBlur() {
		// 延迟关闭，让点击事件先触发
		setTimeout(() => {
			showCommands.value = false
		}, 200)
	}

	function selectCommand(cmd) {
		inputText.value = cmd
		showCommands.value = false
	}

	// ============ 发送 ============
	function handleSend() {
		const text = inputText.value.trim()
		if (!text) return
		emit('send', text)
		inputText.value = ''
		showCommands.value = false
	}

	// ============ 语音（暂占位） ============
	function handleVoice() {
		uni.showToast({ title: '语音功能开发中', icon: 'none', duration: 1500 })
	}

	function handleMore() {
		uni.showActionSheet({
			itemList: ['新建对话', '切换用户', '清空对话'],
			success: (res) => {
				if (res.tapIndex === 0) {
					uni.showToast({ title: '新建对话功能开发中', icon: 'none' })
				} else if (res.tapIndex === 1) {
					emit('send', '切换用户 新用户')
				} else if (res.tapIndex === 2) {
					emit('send', 'quit')
				}
			}
		})
	}
</script>

<style lang="scss" scoped>
	.input-bar {
		background-color: #fff;
		border-top: 1px solid #eee;
		padding: 8px 10px;
	}

	// ============ 命令补全 ============
	.command-hints {
		background-color: #fff;
		border-radius: 12px;
		box-shadow: 0 2px 12px rgba(0,0,0,0.1);
		margin-bottom: 6px;
		overflow: hidden;
		max-height: 220px;
		overflow-y: auto;
	}

	.command-item {
		display: flex;
		align-items: center;
		padding: 10px 14px;
		border-bottom: 1px solid #f5f5f5;

		&:active {
			background-color: #f0f7ff;
		}

		.cmd-trigger {
			font-size: 14px;
			font-weight: 600;
			color: #007aff;
			font-family: monospace;
			width: 100px;
		}

		.cmd-desc {
			font-size: 13px;
			color: #888;
		}
	}

	// ============ 输入行 ============
	.input-row {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.input-btn {
		width: 36px;
		height: 36px;
		display: flex;
		align-items: center;
		justify-content: center;
		border-radius: 50%;

		&:active {
			background-color: #f0f0f0;
		}

		.btn-icon {
			font-size: 18px;
		}
	}

	.input-wrapper {
		flex: 1;
		background-color: #f5f6fa;
		border-radius: 20px;
		padding: 0 14px;
		height: 38px;
		display: flex;
		align-items: center;
	}

	.input-field {
		flex: 1;
		height: 38px;
		min-height: 38px;
		line-height: 38px;
		font-size: 14px;
		color: #333;
		box-sizing: border-box;
	}

	.send-btn {
		width: 36px;
		height: 36px;
		border-radius: 50%;
		background-color: #007aff;
		display: flex;
		align-items: center;
		justify-content: center;

		&:active {
			opacity: 0.8;
		}

		.send-icon {
			font-size: 14px;
			color: #fff;
		}
	}
</style>
