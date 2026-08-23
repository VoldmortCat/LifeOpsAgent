<template>
	<view class="bubble-wrapper" :class="message.role === 'user' ? 'user-wrapper' : 'agent-wrapper'">

		<!-- 用户消息 -->
		<view v-if="message.role === 'user'" class="bubble user-bubble">
			<text class="bubble-text">{{ message.content }}</text>
			<text class="bubble-time">{{ formatTime(message.timestamp) }}</text>
		</view>

		<!-- Agent 消息 -->
		<view v-else class="bubble agent-bubble">
			<!-- 思考过程（可折叠） -->
			<view v-if="message.thinking" class="thinking-block">
				<view class="thinking-header" @click="showThinking = !showThinking">
					<text class="thinking-icon">💭</text>
					<text class="thinking-label">思考过程</text>
					<text class="thinking-arrow">{{ showThinking ? '▲' : '▼' }}</text>
				</view>
				<view v-if="showThinking" class="thinking-content">
					<text>{{ message.thinking }}</text>
				</view>
			</view>

			<!-- 工具调用追踪 -->
			<view v-if="message.toolsUsed && message.toolsUsed.length > 0" class="tools-block">
				<view
					v-for="(tool, tIdx) in message.toolsUsed"
					:key="tIdx"
					class="tool-card"
				>
					<text class="tool-icon">🔧</text>
					<text class="tool-name">{{ tool.name }}</text>
					<text class="tool-status" :class="tool.status">{{ tool.status === 'done' ? '✅' : '⏳' }}</text>
				</view>
			</view>

			<!-- 正文内容（Markdown 渲染） -->
			<view class="content-block">
				<rich-text :nodes="renderedNodes"></rich-text>
			</view>

			<!-- 百度地图链接卡片（从回复文本中检测地图链接） -->
			<MapLink v-if="mapLink" :content="message.content" />

			<!-- 时间 -->
			<text class="bubble-time">{{ formatTime(message.timestamp) }}</text>
		</view>

	</view>
</template>

<script setup>
	import { ref, computed } from 'vue'
	import { parseMarkdown } from '@/utils/markdown.js'
	import MapLink from './MapLink.vue'

	const props = defineProps({
		message: {
			type: Object,
			required: true
		},
		isLast: {
			type: Boolean,
			default: false
		}
	})

	const showThinking = ref(false)

	// 检测回复中是否包含百度地图链接
	const mapLink = computed(() => {
		if (props.message.role !== 'agent') return false
		return /https?:\/\/map\.baidu\.com\//.test(props.message.content || '')
	})

	// Markdown 渲染
	const renderedNodes = computed(() => {
		if (props.message.role === 'user') return []
		return parseMarkdown(props.message.content || '')
	})

	function formatTime(ts) {
		if (!ts) return ''
		const d = new Date(ts)
		const h = String(d.getHours()).padStart(2, '0')
		const m = String(d.getMinutes()).padStart(2, '0')
		return `${h}:${m}`
	}
</script>

<style lang="scss" scoped>
	.bubble-wrapper {
		padding: 6px 0;
	}

	.user-wrapper {
		display: flex;
		justify-content: flex-end;
	}

	.agent-wrapper {
		display: flex;
		justify-content: flex-start;
	}

	.bubble {
		max-width: 82%;
		padding: 12px 14px;
		border-radius: 16px;
		position: relative;
	}

	.user-bubble {
		background: linear-gradient(135deg, #007aff, #5856d6);
		border-bottom-right-radius: 4px;

		.bubble-text {
			font-size: 14px;
			color: #fff;
			line-height: 1.6;
			word-break: break-all;
		}

		.bubble-time {
			font-size: 10px;
			color: rgba(255,255,255,0.6);
			margin-top: 4px;
			display: block;
			text-align: right;
		}
	}

	.agent-bubble {
		background-color: #fff;
		border-bottom-left-radius: 4px;
		box-shadow: 0 1px 4px rgba(0,0,0,0.06);

		.content-block {
			font-size: 14px;
			color: #333;
			line-height: 1.7;
			min-height: 10px;
		}

		.bubble-time {
			font-size: 10px;
			color: #bbb;
			margin-top: 6px;
			display: block;
			text-align: left;
		}
	}

	// 思考过程
	.thinking-block {
		margin-bottom: 8px;
		padding: 8px 10px;
		background-color: #f9f9fb;
		border-radius: 8px;
		border-left: 3px solid #ffa726;
	}

	.thinking-header {
		display: flex;
		align-items: center;
		gap: 4px;
	}

	.thinking-icon { font-size: 14px; }
	.thinking-label { font-size: 12px; color: #999; }
	.thinking-arrow { font-size: 10px; color: #bbb; margin-left: auto; }

	.thinking-content {
		margin-top: 6px;
		padding-top: 6px;
		border-top: 1px dashed #e8e8e8;

		text {
			font-size: 12px;
			color: #888;
			line-height: 1.6;
			font-style: italic;
		}
	}

	// 工具调用卡片
	.tools-block {
		margin-bottom: 8px;
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
	}

	.tool-card {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 4px 8px;
		background-color: #f0f7ff;
		border-radius: 6px;
		border: 1px solid #e0edff;

		.tool-icon { font-size: 12px; }
		.tool-name { font-size: 11px; color: #555; }
		.tool-status { font-size: 10px; }
	}

	// ============ Markdown 渲染样式（通过全局样式配合） ============
	:deep(.md-h1) { font-size: 18px; font-weight: 700; margin: 8px 0; color: #222; }
	:deep(.md-h2) { font-size: 16px; font-weight: 600; margin: 6px 0; color: #333; }
	:deep(.md-h3) { font-size: 15px; font-weight: 600; margin: 4px 0; color: #444; }
	:deep(.md-li) { font-size: 14px; padding: 2px 0 2px 8px; color: #555; }
	:deep(.md-quote) { font-size: 13px; color: #888; padding: 4px 10px; border-left: 3px solid #007aff; background: #f8f9fb; margin: 4px 0; border-radius: 4px; }
	:deep(.md-table-row) { font-size: 12px; font-family: monospace; color: #666; }
	:deep(.code-block) { background: #282c34; color: #abb2bf; padding: 10px 12px; border-radius: 8px; font-size: 12px; font-family: monospace; overflow-x: auto; margin: 6px 0; white-space: pre-wrap; }
</style>
