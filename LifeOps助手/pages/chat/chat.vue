<template>
	<view class="chat-page">
		<!-- 消息列表 -->
		<scroll-view
			class="message-list"
			scroll-y
			:scroll-into-view="scrollToId"
			:scroll-with-animation="true"
		>
			<!-- 空状态引导 -->
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

			<!-- 消息气泡 -->
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

			<!-- 流式输出指示器 -->
			<view v-if="chatStore.isStreaming" class="streaming-indicator">
				<view class="typing-dot"></view>
				<view class="typing-dot"></view>
				<view class="typing-dot"></view>
			</view>

			<view class="bottom-spacer"></view>
		</scroll-view>

		<!-- 输入栏 -->
		<InputBar @send="handleSend" />
	</view>
</template>

<script setup>
	import { ref, watch, nextTick, onMounted } from 'vue'
	import { useChatStore } from '@/store/chat.js'
	import MessageBubble from '@/components/MessageBubble.vue'
	import InputBar from '@/components/InputBar.vue'

	const chatStore = useChatStore()
	const scrollToId = ref('')

	onMounted(() => {
		if (!chatStore.isConnected) {
			chatStore.connect('default')
		}
	})

	function handleSend(content) {
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
</script>

<style lang="scss" scoped>
	.chat-page {
		height: 100%;
		display: flex;
		flex-direction: column;
		background-color: #f5f6fa;
	}

	.message-list {
		flex: 1;
		padding: 12px 16px;
		overflow-y: auto;
	}

	// 空状态
	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		padding-top: 50px;
	}

	.empty-logo {
		width: 72px;
		height: 72px;
		border-radius: 18px;
		margin-bottom: 14px;
	}

	.empty-title {
		font-size: 22px;
		font-weight: 700;
		color: #222;
		margin-bottom: 4px;
	}

	.empty-desc {
		font-size: 14px;
		color: #999;
		margin-bottom: 28px;
	}

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

		&:active {
			background-color: #f5f5f5;
			border-color: #007aff;
		}
	}

	// 流式输出动画
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
