<script>
	export default {
		onLaunch: function() {
			console.log('LifeOps Agent 启动')
			// 检查是否已登录
			const token = uni.getStorageSync('auth_token')
			const user = uni.getStorageSync('auth_user')

			// 获取当前页面路由
			const pages = getCurrentPages()
			const currentRoute = pages.length > 0 ? pages[0].route : ''

			if (token && user) {
				// 已登录，如果当前是登录页，跳转到主页面
				if (currentRoute === 'pages/login/login') {
					uni.switchTab({ url: '/pages/index/index' })
				}
			} else {
				// 未登录，如果当前不是登录页，跳转到登录页
				if (currentRoute !== 'pages/login/login' && currentRoute !== '') {
					uni.reLaunch({ url: '/pages/login/login' })
				}
			}
		},
		onShow: function() {
			console.log('LifeOps Agent 前台展示')
		},
		onHide: function() {
			console.log('LifeOps Agent 后台隐藏')
		}
	}
</script>

<style lang="scss">
	@import "@/uni.scss";

	/* 全局样式重置 */
	page {
		height: 100%;
		background-color: #f5f6fa;
		font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
	}

	view, text, image, input, button, scroll-view {
		box-sizing: border-box;
		margin: 0;
		padding: 0;
	}

	/* 滚动条隐藏 */
	::-webkit-scrollbar {
		display: none;
		width: 0 !important;
		height: 0 !important;
	}

	/* 遮罩动画 */
	@keyframes fadeIn {
		from { opacity: 0; }
		to { opacity: 1; }
	}
	@keyframes fadeOut {
		from { opacity: 1; }
		to { opacity: 0; }
	}

	/* 抽屉滑入 */
	@keyframes slideInLeft {
		from { transform: translateX(-100%); }
		to { transform: translateX(0); }
	}
	@keyframes slideInRight {
		from { transform: translateX(100%); }
		to { transform: translateX(0); }
	}
</style>