import { defineConfig } from 'vite'
import uni from '@dcloudio/vite-plugin-uni'

export default defineConfig({
	plugins: [uni()],
	server: {
		port: 8080,
		proxy: {
			'/api': {
				target: 'http://localhost:8000',
				changeOrigin: true
			},
			// WebSocket 聊天代理（本地开发）
			'/chat': {
				target: 'ws://localhost:8000',
				ws: true,
				changeOrigin: true
			}
		}
	}
})
