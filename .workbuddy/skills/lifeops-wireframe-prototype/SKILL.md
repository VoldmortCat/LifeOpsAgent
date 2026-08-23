---
name: lifeops-wireframe-prototype
description: "This skill generates low-fidelity, hand-drawn sketch wireframe prototypes (Axure RP style) as a single self-contained HTML file, specialized for the LifeOps project (AI toolbox: 智能管家 / 账单中心 / 文档中心 / 个人中心 plus chat drawer). Use it when the user wants to visualize UI pages, produce product-design or course deliverables, or create clickable sketch wireframes for LifeOps. It embeds the sketch filter technique (SVG feTurbulence plus feDisplacementMap), multi-page tab navigation, and reusable page templates (nav plus sidebar list, chat, dashboard stats or charts, settings form, help docs)."
agent_created: true
---

# LifeOps Wireframe Prototype (草图风低保真线框)

## Overview

Generate a single self-contained `.html` file containing a multi-page, Axure-RP-style **low-fidelity
wireframe** with a hand-drawn "sketch" aesthetic. The output is clickable (tab navigation between pages),
needs no network or build step, and opens directly in a browser — ideal for product-design course
submissions, interview demos, and design reviews. The skill is pre-loaded with LifeOps's real page
structure so prototypes stay faithful to the actual product.

## When to Use

Trigger this skill when the user asks, in any phrasing, to:
- "画个原型 / 线框 / 草图 / wireframe / 低保真原型"
- "把 LifeOps 的页面做成原型 / 线框图"
- "生成产品分析设计课的原型 / 交作业用的界面图"
- "做一个 Axure 风格 / 手绘风 的页面示意"
- Visualize UI for LifeOps (智能管家 / 账单中心 / 文档中心 / 个人中心 / 对话抽屉)

## Core Technique: The Sketch Look

The hand-drawn look comes from a single SVG filter applied to the whole prototype via CSS
`filter:url(#sketch)`. No external assets required.

```html
<svg width="0" height="0" style="position:absolute">
  <filter id="sketch">
    <feTurbulence type="fractalNoise" baseFrequency="0.018" numOctaves="3" seed="7" result="n"/>
    <feDisplacementMap in="SourceGraphic" in2="n" scale="2.4" xChannelSelector="R" yChannelSelector="G"/>
  </filter>
</svg>
```

Apply it with `.sketch{filter:url(#sketch);}` wrapping every `.screen`.

**Style tokens (light, friendly, paper-like):**
- `--ink:#2b2b2b; --ink2:#555; --paper:#f5f4f0; --line:#3a3a3a;`
- Page background `#e9e8e3`, frames `2.5px solid var(--ink)`, rounded `10px`.
- Font stack: `"Comic Sans MS","Segoe Print","PingFang SC","Microsoft YaHei",sans-serif` (hand-drawn feel; falls back to PingFang for Chinese).
- Avoid solid color fills for data — use **dashed borders, hatched boxes, and labels** to communicate structure, not visual polish.

## Workflow

1. **Confirm scope.** Identify which LifeOps pages to include. Default set (5 pages):
   智能管家(对话), 账单中心, 文档中心, 个人中心, 帮助/设置. Trim or extend per the user's ask.
2. **Pull the page structure.** Read `references/lifeops-pages.md` (canonical real-page layout) so each
   wireframe matches the actual UI (topbar, tab bar, key components).
3. **Start from the template.** Copy `assets/sketch-wireframe-template.html` as the base — it already has
   the sketch filter, `.screen` switching logic (`go(page)`), topbar, sidebar, and the 5 page scaffolds.
4. **Fill each page.** Use the component primitives below. Keep labels in Chinese, use emoji as lightweight
   icons, keep copy faithful to LifeOps (e.g. 账单中心 stats: 本月支出/收入; 智能管家 empty-state 4 个快捷按钮).
5. **Verify.** Open in a browser, click every tab, confirm all pages render and the sketch filter applies.
6. **Deliver.** Save as `LifeOps 原型_<风格>.html` in the project root and present the file.

## Component Primitives (reuse these classes)

- **Topbar** `.topbar` — left logo mark, center nav tabs (`.nav a` with `.active`), right status chip.
- **Sidebar** `.sidebar` — category list (`.cat` with count `.n`) + "＋ 新建" dashed button.
- **List/Card** `.cards` / `.card` — `.row1` tags, `.ttl` title, `.ct` content box, `.ai` AI note (left border), `.row2` meta + actions.
- **Chat** `.chat` — `.chat-h`, `.chat-body` with `.msg.ai`/`.msg.me` (use `.who` for speaker), `.chat-in` textarea + send button.
- **Dashboard** `.stats` (4 stat tiles) + `.panel` with `.chart` (bar heights as %) + `.chart-x` labels; `.two` for 2-col.
- **Form** `.form` / `.field` (label + input + `.hint`) + `.acts` buttons.
- **Help** `.help` — `h3` sections, `.step` numbered, `.faq` Q&A blocks, `code` inline.

## Navigation

Pages are stacked `.screen` blocks; only the one with `.show` is visible. The `go(p)` JS toggles classes
and scrolls to top. Keep the `map` object in `go()` in sync with page ids.

## LifeOps Fidelity Notes

- 智能管家 = chat home: empty state has 4 quick buttons (查账单 / 出行规划 / 文档总结 / 省钱目标); messages show a **思考过程** folded block + **工具调用卡片**(🔧 tool ✅) + optional embedded map.
- 账单中心 = 2-col stat cards (支出红 / 收入绿) + category proportion bars + detail list (红/绿 amounts).
- 文档中心 = document list + preview modal.
- 个人中心 = config forms: 邮箱配置 / 出行偏好 / 账单导入.
- Use LifeOps brand-agnostic sketch style (no real gradient/colors — it's low-fi), but keep the **red=支出 / green=收入** semantic convention as labels.

## Resources

- `references/lifeops-pages.md` — canonical LifeOps page structure (tabs, components, key copy) extracted from the real `LifeOps助手/` source.
- `assets/sketch-wireframe-template.html` — ready-to-copy base: sketch filter, 5-page scaffold, `go()` switcher, all primitive classes. Duplicate and fill.

## Output Contract

Produce exactly one `.html` file: fully self-contained (inline CSS + SVG filter + vanilla JS), opens offline,
all tabs clickable, faithful to LifeOps real pages. Report the file path when done.
