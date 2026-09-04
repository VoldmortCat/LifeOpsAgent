<template>
	<view class="docs-page">
		<!-- 头部操作区 -->
		<view class="docs-header">
			<text class="docs-title">文档中心</text>
			<view class="header-actions">
				<view class="header-btn" @click="handleImport">
					<text class="btn-icon">📤</text>
					<text class="btn-label">导入</text>
				</view>
				<view class="header-btn" @click="handleRagStatus">
					<text class="btn-icon">📊</text>
					<text class="btn-label">监控</text>
				</view>
				<view class="header-btn" @click="refreshList">
					<text class="btn-icon">🔄</text>
					<text class="btn-label">刷新</text>
				</view>
			</view>
		</view>

		<!-- 加载中 -->
		<view v-if="loading" class="loading-box">
			<text class="loading-text">⏳ 加载文档列表...</text>
		</view>

		<template v-else>
			<scroll-view class="docs-scroll" scroll-y>
				<!-- 按分类展示 -->
				<view v-for="(catDocs, catName) in categories" :key="catName" class="cat-section">
					<view class="cat-header">
						<text class="cat-icon">{{ catIcon(catName) }}</text>
						<text class="cat-title">{{ catName }}</text>
						<text class="cat-count">{{ catDocs.length }} 个文件</text>
					</view>

					<view
						v-for="doc in catDocs"
						:key="doc.path"
						class="doc-item"
						@click="previewDoc(doc)"
					>
						<view class="doc-item-left">
							<text class="doc-icon">{{ fileIcon(doc.ext) }}</text>
							<view class="doc-info">
								<text class="doc-name">{{ doc.name }}</text>
								<text class="doc-meta">{{ formatSize(doc.size) }} · {{ doc.modified }}</text>
							</view>
						</view>
						<text class="doc-arrow">›</text>
					</view>
				</view>

				<!-- 空状态 -->
				<view v-if="totalDocs === 0" class="empty-state">
					<text class="empty-icon">📄</text>
					<text class="empty-title">暂无文档</text>
					<text class="empty-desc">点击右上角「导入」按钮添加知识库文档</text>
					<text class="empty-desc">支持 MD / PDF / TXT / CSV / JSON / YAML 格式</text>
				</view>

				<view class="bottom-spacer"></view>
			</scroll-view>
		</template>

		<!-- 文档预览弹窗 -->
		<view v-if="showPreview" class="preview-mask" @click="showPreview = false">
			<view class="preview-panel" @click.stop>
				<view class="preview-header">
					<text class="preview-title">{{ previewDocItem?.name }}</text>
					<text class="preview-close" @click="showPreview = false">✕</text>
				</view>
				<scroll-view class="preview-body" scroll-y>
					<text v-if="previewLoading" class="preview-loading">⏳ 加载中...</text>
					<text v-else class="preview-content">{{ previewContent }}</text>
				</scroll-view>
			</view>
		</view>
	</view>
</template>

<script setup>
	import { ref, reactive, onMounted } from 'vue'
	import { getDocList, uploadDocument, getDocPreview, getRagStatus } from '@/utils/api.js'

	const loading = ref(true)
	const totalDocs = ref(0)
	const categories = ref({})

	const showPreview = ref(false)
	const previewLoading = ref(false)
	const previewDocItem = ref(null)
	const previewContent = ref('')

	function catIcon(name) {
		const m = { 'food': '🍜', 'general': '🗺', 'other': '📁', '美食': '🍜', '通用': '🗺', '其他': '📁', '未分类': '📂' }
		return m[name] || '📂'
	}

	function fileIcon(ext) {
		const m = { '.md': '📝', '.pdf': '📕', '.txt': '📄', '.csv': '📊', '.json': '⚙️', '.yml': '🔧', '.yaml': '🔧' }
		return m[ext] || '📎'
	}

	function formatSize(bytes) {
		if (bytes < 1024) return bytes + ' B'
		if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
		return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
	}

	async function refreshList() {
		loading.value = true
		await loadList()
	}

	async function loadList() {
		try {
			const data = await getDocList()
			totalDocs.value = data.total
			categories.value = data.categories || {}
			if (data.list && data.list.length > 0 && !data.categories) {
				categories.value = { '全部文档': data.list }
			}
		} catch (e) {
			console.error('文档列表加载失败:', e)
			uni.showToast({ title: '加载失败，请检查后端', icon: 'none' })
		} finally {
			loading.value = false
		}
	}

	function handleImport() {
		uni.showActionSheet({
			itemList: ['从相册/文件选择', '导入到美食库', '导入到通用库', '导入到其他'],
			success: (res) => {
				const categoryMap = { 0: 'other', 1: 'food', 2: 'general', 3: 'other' }
				const category = categoryMap[res.tapIndex] || 'other'
				pickFile(category)
			}
		})
	}

	function pickFile(category) {
		uni.chooseFile({
			count: 1,
			extension: ['.md'],
			success: async (res) => {
				const file = res.tempFiles[0]
				if (!file) return
				uni.showLoading({ title: '上传中...' })
				try {
					const result = await uploadDocument(file.path, category)
					uni.hideLoading()
					if (result.ok) {
						uni.showToast({ title: '导入成功', icon: 'success' })
						await loadList()
					} else {
						uni.showToast({ title: result.error || '导入失败', icon: 'none' })
					}
				} catch (e) {
					uni.hideLoading()
					uni.showToast({ title: '上传失败: ' + (e.message || '网络错误'), icon: 'none' })
				}
			}
		})
	}

	async function previewDoc(doc) {
		previewDocItem.value = doc
		const ext = doc.ext || ''
		if (ext === '.pdf' || ext === '.png' || ext === '.jpg' || ext === '.jpeg') {
			// 二进制文件：新标签页直接打开
			const host = uni.getStorageSync('api_host') || 'localhost'
			const port = uni.getStorageSync('api_port') || '8000'
			const fileUrl = `http://${host}:${port}/api/docs/file/${encodeURIComponent(doc.path)}`
			// #ifdef H5
			window.open(fileUrl, '_blank')
			// #endif
			// #ifdef MP-WEIXIN
			uni.downloadFile({
				url: fileUrl,
				success: (res) => {
					uni.openDocument({ filePath: res.tempFilePath, showMenu: true })
				}
			})
			// #endif
			return
		}

		showPreview.value = true
		previewLoading.value = true
		previewContent.value = ''
		try {
			const data = await getDocPreview(doc.path)
			if (data.is_binary) {
				previewContent.value = `[二进制文件，请通过文件列表直接打开查看]`
			} else {
				previewContent.value = data.content || '(空文件)'
			}
		} catch (e) {
			previewContent.value = '预览失败: ' + (e.message || '网络错误')
		} finally {
			previewLoading.value = false
		}
	}

	async function handleRagStatus() {
		try {
			const data = await getRagStatus()
			uni.showModal({
				title: 'RAG 监控',
				content: JSON.stringify(data, null, 2),
				showCancel: false
			})
		} catch (e) {
			uni.showToast({ title: '获取失败，请确保后端已启动', icon: 'none' })
		}
	}

	onMounted(() => {
		loadList()
	})
</script>

<style lang="scss" scoped>
	.docs-page {
		height: 100%;
		display: flex;
		flex-direction: column;
		background-color: #f5f6fa;
	}

	.docs-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 12px 16px;
		background-color: #fff;
		border-bottom: 1px solid #eee;
	}

	.docs-title {
		font-size: 18px;
		font-weight: 700;
		color: #222;
	}

	.header-actions {
		display: flex;
		gap: 12px;
	}

	.header-btn {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 6px 10px;
		border-radius: 8px;
		background-color: #f5f6fa;

		&:active { background-color: #e8e8e8; }

		.btn-icon { font-size: 16px; }
		.btn-label { font-size: 12px; color: #555; }
	}

	.loading-box {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: center;

		.loading-text { font-size: 14px; color: #999; }
	}

	.docs-scroll {
		flex: 1;
		padding: 12px;
		overflow-y: auto;
	}

	.cat-section {
		margin-bottom: 16px;
	}

	.cat-header {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-bottom: 8px;
		padding: 0 4px;
	}

	.cat-icon { font-size: 18px; }
	.cat-title { font-size: 15px; font-weight: 600; color: #333; }
	.cat-count { font-size: 11px; color: #bbb; margin-left: auto; }

	.doc-item {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 12px 14px;
		background-color: #fff;
		border-radius: 10px;
		margin-bottom: 6px;

		&:active { background-color: #f8f9fb; }
	}

	.doc-item-left {
		display: flex;
		align-items: center;
		gap: 10px;
		flex: 1;
		overflow: hidden;
	}

	.doc-icon { font-size: 24px; flex-shrink: 0; }

	.doc-info {
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.doc-name {
		font-size: 14px;
		color: #333;
		font-weight: 500;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.doc-meta {
		font-size: 11px;
		color: #bbb;
		margin-top: 2px;
	}

	.doc-arrow {
		font-size: 18px;
		color: #ccc;
		flex-shrink: 0;
	}

	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		padding-top: 80px;
	}

	.empty-icon { font-size: 48px; margin-bottom: 16px; }
	.empty-title { font-size: 17px; color: #555; margin-bottom: 6px; }
	.empty-desc { font-size: 13px; color: #bbb; margin-bottom: 4px; }

	// 预览弹窗
	.preview-mask {
		position: fixed;
		top: 0;
		left: 0;
		right: 0;
		bottom: 0;
		background-color: rgba(0, 0, 0, 0.5);
		z-index: 999;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 20px;
	}

	.preview-panel {
		width: 100%;
		max-height: 80vh;
		background-color: #fff;
		border-radius: 14px;
		overflow: hidden;
		display: flex;
		flex-direction: column;
	}

	.preview-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 14px 16px;
		border-bottom: 1px solid #eee;
	}

	.preview-title {
		font-size: 15px;
		font-weight: 600;
		color: #222;
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.preview-close {
		font-size: 18px;
		color: #999;
		padding: 0 4px;
	}

	.preview-body {
		padding: 16px;
		max-height: 65vh;
		overflow-y: auto;
	}

	.preview-loading {
		font-size: 13px;
		color: #bbb;
	}

	.preview-content {
		font-size: 13px;
		color: #444;
		line-height: 1.7;
		white-space: pre-wrap;
		word-break: break-all;
	}

	.bottom-spacer { height: 30px; }
</style>
