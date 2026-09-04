<template>
	<view class="login-page">
		<view class="login-container">
			<!-- Logo -->
			<view class="login-logo">
				<image class="logo-img" src="/static/logo.png" mode="aspectFit"></image>
				<text class="logo-title">LifeOps Agent</text>
				<text class="logo-desc">智能生活管家</text>
			</view>

			<!-- 登录/注册切换 -->
			<view class="tab-bar">
				<view
					class="tab-item"
					:class="{ active: tab === 'login' }"
					@click="tab = 'login'"
				>
					<text>登录</text>
				</view>
				<view
					class="tab-item"
					:class="{ active: tab === 'register' }"
					@click="tab = 'register'"
				>
					<text>注册</text>
				</view>
			</view>

			<!-- 登录表单 -->
			<view v-if="tab === 'login'" class="form-box">
				<view class="form-item">
					<text class="form-label">用户名</text>
					<input
						class="form-input"
						v-model="loginForm.username"
						placeholder="请输入用户名"
						autocomplete="username"
					/>
				</view>
				<view class="form-item">
					<text class="form-label">密码</text>
					<input
						class="form-input"
						v-model="loginForm.password"
						type="password"
						placeholder="请输入密码"
						autocomplete="current-password"
						@confirm="handleLogin"
					/>
				</view>

				<view
					class="submit-btn"
					:class="{ loading: loginLoading }"
					@click="handleLogin"
				>
					<text>{{ loginLoading ? '登录中...' : '登 录' }}</text>
				</view>

				<view v-if="loginError" class="error-msg">
					<text>{{ loginError }}</text>
				</view>
			</view>

			<!-- 注册表单 -->
			<view v-if="tab === 'register'" class="form-box">
				<view class="form-item">
					<text class="form-label">用户名</text>
					<input
						class="form-input"
						v-model="regForm.username"
						placeholder="至少2个字符"
						autocomplete="username"
					/>
				</view>
				<view class="form-item">
					<text class="form-label">昵称</text>
					<input
						class="form-input"
						v-model="regForm.displayName"
						placeholder="可选，显示用"
					/>
				</view>
				<view class="form-item">
					<text class="form-label">密码</text>
					<input
						class="form-input"
						v-model="regForm.password"
						type="password"
						placeholder="至少4个字符"
						autocomplete="new-password"
					/>
				</view>
				<view class="form-item">
					<text class="form-label">确认密码</text>
					<input
						class="form-input"
						v-model="regForm.confirmPassword"
						type="password"
						placeholder="再次输入密码"
						autocomplete="new-password"
						@confirm="handleRegister"
					/>
				</view>

				<view
					class="submit-btn"
					:class="{ loading: regLoading }"
					@click="handleRegister"
				>
					<text>{{ regLoading ? '注册中...' : '注 册' }}</text>
				</view>

				<view v-if="regError" class="error-msg">
					<text>{{ regError }}</text>
				</view>
			</view>
		</view>
	</view>
</template>

<script setup>
	import { ref, reactive } from 'vue'
	import { useAuthStore } from '@/store/auth.js'

	const authStore = useAuthStore()

	const tab = ref('login')

	const loginForm = reactive({ username: '', password: '' })
	const regForm = reactive({ username: '', displayName: '', password: '', confirmPassword: '' })

	const loginLoading = ref(false)
	const regLoading = ref(false)
	const loginError = ref('')
	const regError = ref('')

	async function handleLogin() {
		loginError.value = ''
		if (!loginForm.username.trim() || !loginForm.password.trim()) {
			loginError.value = '请输入用户名和密码'
			return
		}
		loginLoading.value = true
		try {
			const result = await authStore.doLogin(loginForm.username.trim(), loginForm.password)
			if (result.ok) {
				uni.switchTab({ url: '/pages/index/index' })
			} else {
				loginError.value = result.error || '登录失败'
			}
		} catch (e) {
			loginError.value = '网络错误，请检查后端是否启动'
		} finally {
			loginLoading.value = false
		}
	}

	async function handleRegister() {
		regError.value = ''
		if (!regForm.username.trim()) {
			regError.value = '请输入用户名'
			return
		}
		if (regForm.username.trim().length < 2) {
			regError.value = '用户名至少2个字符'
			return
		}
		if (!regForm.password) {
			regError.value = '请输入密码'
			return
		}
		if (regForm.password.length < 4) {
			regError.value = '密码至少4个字符'
			return
		}
		if (regForm.password !== regForm.confirmPassword) {
			regError.value = '两次密码不一致'
			return
		}
		regLoading.value = true
		try {
			const result = await authStore.doRegister(
				regForm.username.trim(),
				regForm.password,
				regForm.displayName.trim()
			)
			if (result.ok) {
				uni.switchTab({ url: '/pages/index/index' })
			} else {
				regError.value = result.error || '注册失败'
			}
		} catch (e) {
			regError.value = '网络错误，请检查后端是否启动'
		} finally {
			regLoading.value = false
		}
	}
</script>

<style lang="scss" scoped>
	.login-page {
		height: 100vh;
		display: flex;
		align-items: center;
		justify-content: center;
		background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
		padding: 24px;
	}

	.login-container {
		width: 100%;
		max-width: 380px;
		background-color: rgba(255, 255, 255, 0.95);
		border-radius: 20px;
		padding: 32px 24px;
		box-shadow: 0 20px 60px rgba(0, 0, 0, 0.15);
	}

	.login-logo {
		display: flex;
		flex-direction: column;
		align-items: center;
		margin-bottom: 28px;
	}

	.logo-img {
		width: 64px;
		height: 64px;
		border-radius: 16px;
		margin-bottom: 10px;
	}

	.logo-title {
		font-size: 22px;
		font-weight: 700;
		color: #222;
		margin-bottom: 4px;
	}

	.logo-desc {
		font-size: 13px;
		color: #999;
	}

	.tab-bar {
		display: flex;
		background-color: #f5f6fa;
		border-radius: 10px;
		padding: 3px;
		margin-bottom: 20px;
	}

	.tab-item {
		flex: 1;
		text-align: center;
		padding: 8px 0;
		border-radius: 8px;
		font-size: 14px;
		color: #888;
		transition: all 0.2s;

		&.active {
			background-color: #fff;
			color: #007aff;
			font-weight: 600;
			box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
		}
	}

	.form-box {
		display: flex;
		flex-direction: column;
		gap: 14px;
	}

	.form-item {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.form-label {
		font-size: 13px;
		color: #666;
		font-weight: 500;
	}

	.form-input {
		height: 44px;
		border: 1px solid #e5e5e5;
		border-radius: 10px;
		padding: 0 14px;
		font-size: 15px;
		color: #333;
		background-color: #fafafa;

		&:focus {
			border-color: #007aff;
			background-color: #fff;
		}
	}

	.submit-btn {
		height: 46px;
		background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
		border-radius: 12px;
		display: flex;
		align-items: center;
		justify-content: center;
		margin-top: 6px;

		&:active {
			opacity: 0.85;
		}

		&.loading {
			opacity: 0.7;
		}

		text {
			font-size: 16px;
			color: #fff;
			font-weight: 600;
		}
	}

	.error-msg {
		text-align: center;
		padding: 6px;
		background-color: #fff0f0;
		border-radius: 8px;

		text {
			font-size: 12px;
			color: #dd524d;
		}
	}
</style>
