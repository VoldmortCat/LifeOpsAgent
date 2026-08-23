<template>
	<view v-if="url" class="map-link-card" @click="openMapLink">
		<text class="map-link-icon">📍</text>
		<view class="map-link-info">
			<text class="map-link-title">在百度地图中查看</text>
			<text class="map-link-desc">{{ platformHint }}</text>
		</view>
		<text class="map-link-arrow">›</text>
	</view>
</template>

<script setup>
	import { computed } from 'vue'

	const props = defineProps({
		// 消息文本内容，从中提取百度地图链接
		content: {
			type: String,
			default: ''
		}
	})

	// 从消息文本中提取百度地图链接
	const url = computed(() => {
		const match = props.content.match(/https?:\/\/map\.baidu\.com\/[^\s)\]"'<>]+/)
		return match ? match[0] : ''
	})

	// #ifdef H5
	const platformHint = '点击打开百度地图网页版（可看导航、街景、评论）'
	// #endif
	// #ifdef APP-PLUS
	const platformHint = '点击唤起百度地图 App'
	// #endif
	// #ifndef H5 || APP-PLUS
	const platformHint = '复制链接，在浏览器中打开'
	// #endif

	function openMapLink() {
		if (!url.value) return
		// #ifdef H5
		window.open(url.value, '_blank')
		// #endif
		// #ifdef APP-PLUS
		plus.runtime.openURL(url.value)
		// #endif
		// #ifndef H5 || APP-PLUS
		uni.setClipboardData({
			data: url.value,
			success: () => uni.showToast({ title: '链接已复制，请在浏览器中打开', icon: 'none' })
		})
		// #endif
	}
</script>

<style lang="scss" scoped>
	.map-link-card {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-top: 10px;
		padding: 12px 14px;
		background: #f0f7ff;
		border: 1px solid #d8e8ff;
		border-radius: 10px;
	}

	.map-link-icon {
		font-size: 18px;
	}

	.map-link-info {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.map-link-title {
		font-size: 14px;
		font-weight: 600;
		color: #007aff;
	}

	.map-link-desc {
		font-size: 11px;
		color: #999;
	}

	.map-link-arrow {
		font-size: 20px;
		color: #007aff;
	}
</style>