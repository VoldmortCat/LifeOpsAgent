<template>
	<view class="bill-center">
		<!-- 头部 -->
		<view class="bill-header" :style="{ paddingTop: statusBarHeight + 10 + 'px' }">
			<view class="bill-header-row">
				<text class="bill-title">账单中心</text>
				<view class="bill-close" @click="$emit('close')">
					<text class="close-icon">✕</text>
				</view>
			</view>
		</view>

		<!-- 内容区域 -->
		<scroll-view class="bill-content" scroll-y>
			<!-- 时间选择器 -->
			<view class="period-selector">
				<view
					v-for="p in periods"
					:key="p.value"
					class="period-btn"
					:class="{ active: currentPeriod === p.value }"
					@click="currentPeriod = p.value"
				>
					<text>{{ p.label }}</text>
				</view>
			</view>

			<!-- 统计卡片 -->
			<view class="stat-cards">
				<view class="stat-card card-expense">
					<text class="stat-label">总支出</text>
					<text class="stat-value">¥{{ stats.expense }}</text>
				</view>
				<view class="stat-card card-income">
					<text class="stat-label">总收入</text>
					<text class="stat-value">¥{{ stats.income }}</text>
				</view>
				<view class="stat-card card-balance">
					<text class="stat-label">结余</text>
					<text class="stat-value" :class="stats.balance >= 0 ? 'positive' : 'negative'">
						¥{{ stats.balance }}
					</text>
				</view>
				<view class="stat-card card-daily">
					<text class="stat-label">日均消费</text>
					<text class="stat-value">¥{{ stats.dailyAvg }}</text>
				</view>
			</view>

			<!-- 消费趋势图（占位） -->
			<view class="chart-section">
				<text class="section-title">消费趋势</text>
				<view class="chart-placeholder">
					<text class="chart-hint">📈 消费趋势图（连接后端后可渲染 uCharts 图表）</text>
				</view>
			</view>

			<!-- 分类占比（占位） -->
			<view class="chart-section">
				<text class="section-title">分类占比</text>
				<view class="chart-placeholder pie-placeholder">
					<text class="chart-hint">🍩 分类饼图（连接后端后可渲染 uCharts 图表）</text>
				</view>
			</view>

			<!-- 账单明细 -->
			<view class="bill-list-section">
				<text class="section-title">账单明细</text>
				<view v-if="billItems.length > 0" class="bill-list">
					<view v-for="(item, idx) in billItems" :key="idx" class="bill-item">
						<view class="bill-item-left">
							<text class="bill-item-category">{{ item.category }}</text>
							<text class="bill-item-date">{{ item.date }}</text>
						</view>
						<text class="bill-item-amount" :class="item.type === 'income' ? 'amount-income' : 'amount-expense'">
							{{ item.type === 'income' ? '+' : '-' }}¥{{ item.amount }}
						</text>
					</view>
				</view>
				<view v-else class="empty-bill">
					<text class="empty-hint">暂无账单数据</text>
					<text class="empty-sub">在对话中发送 "本月账单汇总" 获取数据</text>
				</view>
			</view>

			<!-- 导出按钮 -->
			<view class="export-btn" @click="handleExport">
				<text>📥 导出账单 CSV</text>
			</view>
		</scroll-view>
	</view>
</template>

<script setup>
	import { ref, reactive } from 'vue'

	defineEmits(['close'])

	const statusBarHeight = ref(20)

	// 获取状态栏高度
	try {
		const info = uni.getSystemInfoSync()
		statusBarHeight.value = info.statusBarHeight || 20
	} catch (e) {}

	// ============ 数据 ============
	const periods = [
		{ label: '本周', value: 'week' },
		{ label: '本月', value: 'month' },
		{ label: '本年', value: 'year' }
	]
	const currentPeriod = ref('month')

	const stats = reactive({
		expense: '0.00',
		income: '0.00',
		balance: '0.00',
		dailyAvg: '0.00'
	})

	// 示例账单明细（连接后端后替换为动态数据）
	const billItems = ref([])

	// ============ 方法 ============
	function handleExport() {
		uni.showToast({ title: '导出功能需连接后端', icon: 'none' })
	}
</script>

<style lang="scss" scoped>
	.bill-center {
		height: 100%;
		display: flex;
		flex-direction: column;
		background-color: #f8f9fb;
	}

	// ============ 头部 ============
	.bill-header {
		background-color: #fff;
		padding: 10px 16px 12px;
		border-bottom: 1px solid #eee;
	}

	.bill-header-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.bill-title {
		font-size: 18px;
		font-weight: 700;
		color: #222;
	}

	.bill-close {
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
	.bill-content {
		flex: 1;
		padding: 12px;
		overflow-y: auto;
	}

	// ============ 时间选择 ============
	.period-selector {
		display: flex;
		background-color: #fff;
		border-radius: 10px;
		padding: 4px;
		margin-bottom: 12px;
	}

	.period-btn {
		flex: 1;
		text-align: center;
		padding: 8px 0;
		border-radius: 8px;
		transition: all 0.2s;

		text {
			font-size: 13px;
			color: #888;
		}

		&.active {
			background-color: #007aff;

			text {
				color: #fff;
				font-weight: 600;
			}
		}
	}

	// ============ 统计卡片 ============
	.stat-cards {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 8px;
		margin-bottom: 12px;
	}

	.stat-card {
		padding: 14px;
		border-radius: 12px;
		background-color: #fff;

		.stat-label {
			font-size: 12px;
			color: #999;
			display: block;
			margin-bottom: 4px;
		}

		.stat-value {
			font-size: 20px;
			font-weight: 700;
			color: #333;

			&.positive { color: #4cd964; }
			&.negative { color: #dd524d; }
		}
	}

	.card-expense .stat-value { color: #dd524d; }
	.card-income .stat-value { color: #4cd964; }

	// ============ 图表占位 ============
	.chart-section {
		margin-bottom: 12px;
	}

	.section-title {
		font-size: 15px;
		font-weight: 600;
		color: #333;
		margin-bottom: 8px;
		display: block;
	}

	.chart-placeholder {
		height: 160px;
		background-color: #fff;
		border-radius: 12px;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.chart-hint {
		font-size: 12px;
		color: #bbb;
	}

	.pie-placeholder {
		height: 180px;
	}

	// ============ 账单明细 ============
	.bill-list-section {
		margin-bottom: 12px;
	}

	.bill-item {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 12px 14px;
		background-color: #fff;
		border-radius: 8px;
		margin-bottom: 4px;
	}

	.bill-item-left {
		display: flex;
		flex-direction: column;
	}

	.bill-item-category {
		font-size: 14px;
		color: #333;
		font-weight: 500;
	}

	.bill-item-date {
		font-size: 11px;
		color: #bbb;
		margin-top: 2px;
	}

	.bill-item-amount {
		font-size: 15px;
		font-weight: 600;
	}

	.amount-expense { color: #dd524d; }
	.amount-income { color: #4cd964; }

	// ============ 空状态 ============
	.empty-bill {
		padding: 30px 0;
		display: flex;
		flex-direction: column;
		align-items: center;
		background-color: #fff;
		border-radius: 12px;
	}

	.empty-hint {
		font-size: 14px;
		color: #999;
	}

	.empty-sub {
		font-size: 12px;
		color: #ccc;
		margin-top: 4px;
	}

	// ============ 导出按钮 ============
	.export-btn {
		text-align: center;
		padding: 12px;
		background-color: #fff;
		border-radius: 10px;
		border: 1px dashed #007aff;
		margin-bottom: 20px;

		&:active {
			background-color: #f0f7ff;
		}

		text {
			font-size: 14px;
			color: #007aff;
			font-weight: 500;
		}
	}
</style>
