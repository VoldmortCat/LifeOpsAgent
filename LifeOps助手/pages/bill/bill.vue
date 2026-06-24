<template>
	<view class="bill-page">
		<!-- 时间选择器 -->
		<view class="period-selector">
			<view
				v-for="p in periods"
				:key="p.value"
				class="period-btn"
				:class="{ active: currentPeriod === p.value }"
				@click="switchPeriod(p.value)"
			>
				<text>{{ p.label }}</text>
			</view>
		</view>

		<!-- 加载中 -->
		<view v-if="loading" class="loading-box">
			<text class="loading-text">⏳ 加载账单数据...</text>
		</view>

		<template v-else>
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

			<scroll-view class="bill-scroll" scroll-y>
				<!-- 消费趋势图 -->
				<view class="chart-section">
					<text class="section-title">消费趋势</text>
					<image
						v-if="chartTrendUrl"
						class="chart-img"
						:src="chartTrendUrl"
						mode="widthFix"
						@click="previewChart(chartTrendUrl)"
					></image>
					<view v-else class="chart-placeholder">
						<text class="chart-hint">暂无趋势数据</text>
					</view>
				</view>

				<!-- 分类占比 -->
				<view class="chart-section">
					<text class="section-title">分类占比</text>
					<view v-if="categories.length > 0" class="category-bars">
						<view v-for="(cat, idx) in categories" :key="idx" class="category-bar-row">
							<text class="cat-name">{{ cat.name }}</text>
							<view class="cat-bar-track">
								<view class="cat-bar-fill" :style="{ width: catPercent(cat.amount) }"></view>
							</view>
							<text class="cat-amount">¥{{ cat.amount }}</text>
						</view>
					</view>
					<view v-else class="chart-placeholder pie-placeholder">
						<text class="chart-hint">暂无分类数据</text>
					</view>
				</view>

				<!-- 账单明细 -->
				<view class="bill-list-section">
					<text class="section-title">账单明细</text>
					<view v-if="billItems.length > 0" class="bill-list">
						<view v-for="(item, idx) in billItems" :key="idx" class="bill-item">
							<view class="bill-item-left">
								<text class="bill-item-category">{{ item.category || item.commodity || '未知' }}</text>
								<text class="bill-item-date">{{ item.date }}</text>
							</view>
							<text class="bill-item-amount" :class="item.type === 'income' ? 'amount-income' : 'amount-expense'">
								{{ item.type === 'income' ? '+' : '-' }}¥{{ item.amount }}
							</text>
						</view>
					</view>
					<view v-else class="empty-bill">
						<text class="empty-hint">暂无账单数据</text>
						<text class="empty-sub">请在对话中发送 "本月账单汇总" 获取数据</text>
					</view>
				</view>

				<view class="bottom-spacer"></view>
			</scroll-view>
		</template>
	</view>
</template>

<script setup>
	import { ref, reactive, onMounted } from 'vue'
	import { getBillSummary, getBillChartUrl } from '@/utils/api.js'

	const periods = [
		{ label: '本周', value: 'week' },
		{ label: '本月', value: 'month' },
		{ label: '本年', value: 'year' }
	]
	const currentPeriod = ref('month')
	const loading = ref(true)

	const stats = reactive({
		expense: '0.00',
		income: '0.00',
		balance: '0.00',
		dailyAvg: '0.00'
	})

	const categories = ref([])
	const billItems = ref([])
	const chartTrendUrl = ref('')
	const chartCategoryUrl = ref('')

	function catPercent(amount) {
		const max = Math.max(...categories.value.map(c => c.amount), 1)
		return ((amount / max) * 100).toFixed(0) + '%'
	}

	function previewChart(url) {
		uni.previewImage({ urls: [url] })
	}

	async function switchPeriod(period) {
		currentPeriod.value = period
		await loadData()
	}

	async function loadData() {
		loading.value = true
		try {
			const data = await getBillSummary(currentPeriod.value)
			stats.expense = data.stats.expense
			stats.income = data.stats.income
			stats.balance = data.stats.balance
			stats.dailyAvg = data.stats.dailyAvg
			categories.value = data.categories || []
			billItems.value = data.items || []
			chartTrendUrl.value = data.charts?.trend ? getBillChartUrl(currentPeriod.value, 'trend') : ''
			chartCategoryUrl.value = data.charts?.category ? getBillChartUrl(currentPeriod.value, 'category') : ''
		} catch (e) {
			console.error('账单数据加载失败:', e)
			uni.showToast({ title: '数据加载失败，请检查后端', icon: 'none' })
		} finally {
			loading.value = false
		}
	}

	onMounted(() => {
		loadData()
	})
</script>

<style lang="scss" scoped>
	.bill-page {
		height: 100%;
		display: flex;
		flex-direction: column;
		background-color: #f5f6fa;
	}

	.loading-box {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: center;

		.loading-text { font-size: 14px; color: #999; }
	}

	.period-selector {
		display: flex;
		background-color: #fff;
		border-radius: 10px;
		padding: 4px;
		margin: 12px;
	}

	.period-btn {
		flex: 1;
		text-align: center;
		padding: 8px 0;
		border-radius: 8px;
		transition: all 0.2s;

		text { font-size: 13px; color: #888; }

		&.active {
			background-color: #007aff;
			text { color: #fff; font-weight: 600; }
		}
	}

	.stat-cards {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 8px;
		padding: 0 12px;
		margin-bottom: 8px;
	}

	.stat-card {
		padding: 14px;
		border-radius: 12px;
		background-color: #fff;

		.stat-label { font-size: 12px; color: #999; display: block; margin-bottom: 4px; }
		.stat-value { font-size: 20px; font-weight: 700; color: #333; }
	}

	.card-expense .stat-value { color: #dd524d; }
	.card-income .stat-value { color: #4cd964; }
	.positive { color: #4cd964; }
	.negative { color: #dd524d; }

	.bill-scroll {
		flex: 1;
		padding: 0 12px;
		overflow-y: auto;
	}

	.chart-section { margin-bottom: 12px; }

	.section-title {
		font-size: 15px;
		font-weight: 600;
		color: #333;
		margin-bottom: 8px;
		display: block;
	}

	.chart-img {
		width: 100%;
		border-radius: 12px;
		background-color: #fff;
	}

	.chart-placeholder {
		height: 160px;
		background-color: #fff;
		border-radius: 12px;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.pie-placeholder { height: 120px; }

	.chart-hint { font-size: 12px; color: #bbb; }

	.category-bars {
		background-color: #fff;
		border-radius: 12px;
		padding: 12px 14px;
	}

	.category-bar-row {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 5px 0;
	}

	.cat-name {
		font-size: 12px;
		color: #555;
		width: 64px;
		flex-shrink: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.cat-bar-track {
		flex: 1;
		height: 10px;
		background-color: #f0f0f0;
		border-radius: 5px;
		overflow: hidden;
	}

	.cat-bar-fill {
		height: 100%;
		background: linear-gradient(90deg, #007aff, #5856d6);
		border-radius: 5px;
		transition: width 0.4s ease;
	}

	.cat-amount {
		font-size: 12px;
		color: #999;
		width: 60px;
		text-align: right;
		flex-shrink: 0;
	}

	.bill-list-section { margin-bottom: 12px; }

	.bill-item {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 12px 14px;
		background-color: #fff;
		border-radius: 8px;
		margin-bottom: 4px;
	}

	.bill-item-left { display: flex; flex-direction: column; }
	.bill-item-category { font-size: 14px; color: #333; font-weight: 500; }
	.bill-item-date { font-size: 11px; color: #bbb; margin-top: 2px; }
	.bill-item-amount { font-size: 15px; font-weight: 600; }
	.amount-expense { color: #dd524d; }
	.amount-income { color: #4cd964; }

	.empty-bill {
		padding: 30px 0;
		display: flex;
		flex-direction: column;
		align-items: center;
		background-color: #fff;
		border-radius: 12px;
	}

	.empty-hint { font-size: 14px; color: #999; }
	.empty-sub { font-size: 12px; color: #ccc; margin-top: 4px; }

	.bottom-spacer { height: 20px; }
</style>
