import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { login, register, getMe } from '@/utils/api.js'

export const useAuthStore = defineStore('auth', () => {
	// ============ 状态 ============
	const token = ref('')
	const user = ref(null)
	const isReady = ref(false)

	// ============ 计算属性 ============
	const isLoggedIn = computed(() => !!token.value && !!user.value)
	const username = computed(() => user.value?.display_name || user.value?.username || '')
	const userId = computed(() => user.value?.id || 0)

	// ============ 初始化 ============
	function init() {
		const savedToken = uni.getStorageSync('auth_token')
		const savedUser = uni.getStorageSync('auth_user')
		if (savedToken && savedUser) {
			token.value = savedToken
			user.value = savedUser
		}
		isReady.value = true
	}

	// ============ 登录/注册 ============
	async function doLogin(username, password) {
		const res = await login(username, password)
		if (res.ok) {
			token.value = res.token
			user.value = res.user
			uni.setStorageSync('auth_token', res.token)
			uni.setStorageSync('auth_user', res.user)
			return { ok: true }
		}
		return { ok: false, error: res.error || '登录失败' }
	}

	async function doRegister(username, password, displayName = '') {
		const res = await register(username, password, displayName)
		if (res.ok) {
			token.value = res.token
			user.value = res.user
			uni.setStorageSync('auth_token', res.token)
			uni.setStorageSync('auth_user', res.user)
			return { ok: true }
		}
		return { ok: false, error: res.error || '注册失败' }
	}

	async function fetchUserInfo() {
		if (!token.value) return null
		try {
			const res = await getMe()
			if (res.ok) {
				user.value = res.user
				uni.setStorageSync('auth_user', res.user)
				return res.user
			}
		} catch (e) {
			console.error('获取用户信息失败:', e)
		}
		return null
	}

	// ============ 登出 ============
	function logout() {
		token.value = ''
		user.value = null
		uni.removeStorageSync('auth_token')
		uni.removeStorageSync('auth_user')
	}

	// 初始化
	init()

	return {
		token,
		user,
		isReady,
		isLoggedIn,
		username,
		userId,
		init,
		doLogin,
		doRegister,
		fetchUserInfo,
		logout,
	}
})
