// 简易 Markdown 渲染器
// 将 Markdown 文本转换为 rich-text nodes 数组

export function parseMarkdown(text) {
	if (!text) return []

	const lines = text.split('\n')
	const nodes = []
	let inCodeBlock = false
	let codeContent = ''
	let codeLang = ''

	for (let i = 0; i < lines.length; i++) {
		const line = lines[i]

		// 代码块
		if (line.startsWith('```')) {
			if (inCodeBlock) {
				nodes.push({
					name: 'pre',
					attrs: { class: 'code-block' },
					children: [{
						type: 'text',
						text: codeContent
					}]
				})
				codeContent = ''
				inCodeBlock = false
			} else {
				inCodeBlock = true
				codeLang = line.slice(3).trim()
			}
			continue
		}

		if (inCodeBlock) {
			codeContent += line + '\n'
			continue
		}

		// 空行
		if (!line.trim()) {
			nodes.push({ name: 'br' })
			continue
		}

		// 标题
		const headingMatch = line.match(/^(#{1,3})\s+(.+)/)
		if (headingMatch) {
			const level = headingMatch[1].length
			nodes.push({
				name: 'h' + level,
				attrs: { class: `md-h${level}` },
				children: parseInline(headingMatch[2])
			})
			continue
		}

		// 无序列表
		const ulMatch = line.match(/^[\-\*]\s+(.+)/)
		if (ulMatch) {
			nodes.push({
				name: 'li',
				attrs: { class: 'md-li' },
				children: parseInline(ulMatch[1])
			})
			continue
		}

		// 表格（简化为预格式文本）
		if (line.startsWith('|') && line.endsWith('|')) {
			nodes.push({
				name: 'p',
				attrs: { class: 'md-table-row' },
				children: parseInline(line)
			})
			continue
		}

		// 引用
		if (line.startsWith('> ')) {
			nodes.push({
				name: 'blockquote',
				attrs: { class: 'md-quote' },
				children: parseInline(line.slice(2))
			})
			continue
		}

		// 普通段落
		nodes.push({
			name: 'p',
			attrs: { class: 'md-p' },
			children: parseInline(line)
		})
	}

	return nodes
}

// 行内解析：粗体、斜体、行内代码
function parseInline(text) {
	if (!text) return [{ type: 'text', text: '' }]

	const result = []
	let remaining = text

	while (remaining.length > 0) {
		// 粗体 **text**
		const boldMatch = remaining.match(/^(.*?)\*\*(.+?)\*\*/)
		if (boldMatch) {
			if (boldMatch[1]) result.push({ type: 'text', text: boldMatch[1] })
			result.push({ type: 'text', text: boldMatch[2], attrs: { style: 'font-weight:bold' } })
			remaining = remaining.slice(boldMatch[0].length)
			continue
		}

		// 行内代码 `code`
		const codeMatch = remaining.match(/^(.*?)`(.+?)`/)
		if (codeMatch) {
			if (codeMatch[1]) result.push({ type: 'text', text: codeMatch[1] })
			result.push({ type: 'text', text: codeMatch[2], attrs: { style: 'background:#f0f0f0;padding:1px 4px;border-radius:2px;font-family:monospace' } })
			remaining = remaining.slice(codeMatch[0].length)
			continue
		}

		// 普通文本
		result.push({ type: 'text', text: remaining })
		break
	}

	return result
}

export default { parseMarkdown }
