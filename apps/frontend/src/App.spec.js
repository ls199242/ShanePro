import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App.vue'

function jsonResponse(body) {
  return {
    ok: true,
    json: vi.fn().mockResolvedValue(body),
  }
}

function streamResponse(frames) {
  const encoder = new TextEncoder()

  return {
    ok: true,
    body: new ReadableStream({
      start(controller) {
        frames.forEach((frame) => {
          controller.enqueue(encoder.encode(frame))
        })
        controller.close()
      },
    }),
  }
}

describe('App', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders successful statuses from both backend services', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse({ data: { service: 'java-api', language: 'Java', status: 'UP' } }))
        .mockResolvedValueOnce(jsonResponse({ data: { service: 'python-api', language: 'Python', status: 'UP' } })),
    )

    const wrapper = mount(App)
    await flushPromises()

    expect(wrapper.text()).toContain('Java API')
    expect(wrapper.text()).toContain('Python API')
    expect(wrapper.text()).toContain('java-api')
    expect(wrapper.text()).toContain('python-api')
    expect(wrapper.text()).toContain('运行中')
  })

  it('renders the site title and keeps the home menu item', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))

    const wrapper = mount(App)

    expect(wrapper.text()).toContain("Shane's Site")
    expect(wrapper.get('nav[aria-label="站点菜单"]').text()).toContain('首页')
    expect(wrapper.get('nav[aria-label="站点菜单"]').text()).toContain('AI 问答')
    expect(wrapper.get('nav[aria-label="站点菜单"]').text()).toContain('文档库')
  })

  it('switches between A warm and C clean themes on the home page', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))

    const wrapper = mount(App)

    expect(wrapper.get('button[aria-label="切换 C 清爽浅色"]').text()).toContain('☾')
    expect(wrapper.attributes('data-theme')).toBeUndefined()

    await wrapper.get('button[aria-label="切换 C 清爽浅色"]').trigger('click')

    expect(wrapper.get('button[aria-label="切换 A 暖色书房"]').text()).toContain('☀')
    expect(wrapper.attributes('data-theme')).toBe('clean')
  })

  it('switches to the AI chat panel from the sidebar', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))

    const wrapper = mount(App)
    const aiButton = wrapper.get('button[aria-label="AI 问答"]')

    await aiButton.trigger('click')

    expect(wrapper.text()).toContain('输入问题后开始会话')
    expect(wrapper.text()).toContain('发送')
  })

  it('switches to the document library from the sidebar', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))

    const wrapper = mount(App)
    await wrapper.get('button[aria-label="文档库"]').trigger('click')

    expect(wrapper.text()).toContain('个人文档库')
    expect(wrapper.text()).toContain('上传文档')
    expect(wrapper.text()).toContain('刷新文档')
  })

  it('uploads and refreshes personal documents from the AI chat panel', async () => {
    const documentSummary = {
      id: 'doc-1',
      filename: 'notes.md',
      content_type: 'text/markdown',
      size_bytes: 128,
      md5: 'ebd0767a0e5594c08c1e2b2f752e8871',
      original_path: '/tmp/uploads/doc-1.md',
      parsed_text_path: '/tmp/parsed/doc-1.txt',
      status: 'ready',
      chunk_count: 2,
      is_failed: false,
      failed_at: null,
      created_at: '2026-06-26T00:00:00+08:00',
      updated_at: '2026-06-26T00:00:00+08:00',
    }
    const uploadedDocument = {
      ...documentSummary,
      id: 'doc-2',
      filename: 'new-notes.md',
      parsed_text_path: null,
      status: 'uploaded',
      chunk_count: 0,
    }
    const parsingDocument = {
      ...uploadedDocument,
      status: 'parsing',
    }
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse({ data: { service: 'java-api', language: 'Java', status: 'UP' } }))
        .mockResolvedValueOnce(jsonResponse({ data: { service: 'python-api', language: 'Python', status: 'UP' } }))
        .mockResolvedValueOnce(jsonResponse({ code: 0, data: [documentSummary] }))
        .mockResolvedValueOnce(jsonResponse({ code: 0, data: { ...uploadedDocument, duplicate: false } }))
        .mockResolvedValueOnce(jsonResponse({ code: 0, data: [uploadedDocument] }))
        .mockResolvedValueOnce(jsonResponse({ code: 0, data: parsingDocument }))
        .mockResolvedValueOnce(jsonResponse({ code: 0, data: [parsingDocument] })),
    )

    const wrapper = mount(App)
    await flushPromises()
    await wrapper.get('button[aria-label="AI 问答"]').trigger('click')

    expect(wrapper.text()).toContain('个人文档库')

    await wrapper.findAll('button').find((button) => button.text() === '刷新文档').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('notes.md')
    expect(wrapper.text()).toContain('2 chunks')

    const input = wrapper.get('input[type="file"]')
    const file = new File(['# hello'], 'new-notes.md', { type: 'text/markdown' })
    Object.defineProperty(input.element, 'files', {
      value: [file],
      configurable: true,
    })
    await input.trigger('change')
    await flushPromises()

    expect(fetch.mock.calls[3][0]).toBe('/python-api/api/documents/upload')
    expect(fetch.mock.calls[3][1].method).toBe('POST')
    expect(fetch.mock.calls[3][1].body).toBeInstanceOf(FormData)
    expect(wrapper.text()).toContain('new-notes.md')
    expect(wrapper.text()).toContain('待处理')

    await wrapper.findAll('button').find((button) => button.text() === '开始处理').trigger('click')
    await flushPromises()

    expect(fetch.mock.calls[5][0]).toBe('/python-api/api/documents/doc-2/process')
    expect(fetch.mock.calls[5][1].method).toBe('POST')
    expect(wrapper.text()).toContain('解析中')
  })

  it('creates a new empty AI chat session while keeping the old session in history', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse({ data: { service: 'java-api', language: 'Java', status: 'UP' } }))
        .mockResolvedValueOnce(jsonResponse({ data: { service: 'python-api', language: 'Python', status: 'UP' } }))
        .mockResolvedValueOnce(streamResponse([
          'event: session\ndata: {"session_id":"backend-session-1"}\n\n',
          'event: on_tool_start\ndata: {"name":"web_search","data":{"input":{"query":"你好"}}}\n\n',
          'event: on_tool_end\ndata: {"name":"web_search","data":{"output":{"status":"success","provider":"tavily","query":"你好","results":[{"title":"Shane Site","url":"https://example.com","snippet":"search result"}]}}}\n\n',
          'event: on_chat_model_stream\ndata: {"name":"model","data":{"thinking":"先判断用户问候。","text":""}}\n\n',
          'event: on_chat_model_stream\ndata: {"name":"model","data":{"text":"你好，"}}\n\n',
          'event: on_chat_model_stream\ndata: {"name":"model","data":{"text":"我是 AI"}}\n\n',
          'event: agent_done\ndata: {"session_id":"backend-session-1","answer":"你好，我是 AI","thinking":"先判断用户问候。","tools":[{"name":"web_search","status":"success","input":{"query":"你好"},"output":{"provider":"tavily","query":"你好","results":[{"title":"Shane Site","url":"https://example.com","snippet":"search result"}]}}],"history":[{"role":"user","content":"你好"},{"role":"assistant","content":"你好，我是 AI","thinking":"先判断用户问候。"}]}\n\n',
        ])),
    )

    const wrapper = mount(App)
    await flushPromises()
    await wrapper.get('button[aria-label="AI 问答"]').trigger('click')
    await wrapper.get('textarea').setValue('你好')
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.text()).toContain('你好，我是 AI')
    expect(wrapper.text()).toContain('思考过程')
    expect(wrapper.text()).toContain('先判断用户问候。')
    expect(wrapper.text()).toContain('工具调用')
    expect(wrapper.text()).toContain('Web 搜索')
    expect(wrapper.text()).toContain('https://example.com')
    expect(wrapper.text()).toContain('backend-session-1')
    expect(wrapper.text()).toContain('第 1 轮')
    expect(JSON.parse(fetch.mock.calls[2][1].body).web_search_enabled).toBe(true)
    expect(wrapper.text()).toContain('"web_search_enabled": true')
    expect(wrapper.get('button[aria-label="关闭联网搜索"]').attributes('disabled')).toBeDefined()

    const newChatButton = wrapper.findAll('button').find((button) => button.text() === '新建对话')
    expect(newChatButton).toBeTruthy()
    await newChatButton.trigger('click')

    expect(wrapper.text()).toContain('尚未建立后端 session')
    expect(wrapper.text()).toContain('输入问题后开始会话')
    expect(wrapper.text()).toContain('发送后展示每一轮入参和出参')
    expect(wrapper.text()).toContain('backend-session-1')
    expect(wrapper.get('button[aria-label="关闭联网搜索"]').attributes('disabled')).toBeUndefined()

    await wrapper.get('button[aria-label="关闭联网搜索"]').trigger('click')
    expect(wrapper.get('button[aria-label="开启联网搜索"]').text()).toContain('联网搜索 关')
  })

  it('sends AI chat with web search disabled from the toolbar toggle', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse({ data: { service: 'java-api', language: 'Java', status: 'UP' } }))
        .mockResolvedValueOnce(jsonResponse({ data: { service: 'python-api', language: 'Python', status: 'UP' } }))
        .mockResolvedValueOnce(streamResponse([
          'event: session\ndata: {"session_id":"no-search-session"}\n\n',
          'event: on_chat_model_stream\ndata: {"name":"model","data":{"text":"当前未启用联网搜索。"}}\n\n',
          'event: agent_done\ndata: {"session_id":"no-search-session","answer":"当前未启用联网搜索。","history":[{"role":"user","content":"查一下最新版本"},{"role":"assistant","content":"当前未启用联网搜索。"}]}\n\n',
        ])),
    )

    const wrapper = mount(App)
    await flushPromises()
    await wrapper.get('button[aria-label="AI 问答"]').trigger('click')
    await wrapper.get('button[aria-label="关闭联网搜索"]').trigger('click')

    expect(wrapper.get('button[aria-label="开启联网搜索"]').text()).toContain('联网搜索 关')

    await wrapper.get('textarea').setValue('查一下最新版本')
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()

    expect(JSON.parse(fetch.mock.calls[2][1].body).web_search_enabled).toBe(false)
    expect(wrapper.text()).toContain('"web_search_enabled": false')
    expect(wrapper.text()).toContain('当前未启用联网搜索。')
    expect(wrapper.get('button[aria-label="开启联网搜索"]').attributes('disabled')).toBeDefined()
  })

  it('submits AI chat with Enter while keeping Shift Enter for line breaks', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse({ data: { service: 'java-api', language: 'Java', status: 'UP' } }))
        .mockResolvedValueOnce(jsonResponse({ data: { service: 'python-api', language: 'Python', status: 'UP' } }))
        .mockResolvedValueOnce(streamResponse([
          'event: session\ndata: {"session_id":"keyboard-session"}\n\n',
          'event: on_chat_model_stream\ndata: {"name":"model","data":{"text":"收到"}}\n\n',
          'event: agent_done\ndata: {"session_id":"keyboard-session","answer":"收到","history":[{"role":"user","content":"回车发送"},{"role":"assistant","content":"收到"}]}\n\n',
        ])),
    )

    const wrapper = mount(App)
    await flushPromises()
    await wrapper.get('button[aria-label="AI 问答"]').trigger('click')
    const textarea = wrapper.get('textarea')

    await textarea.setValue('Shift 换行')
    await textarea.trigger('keydown', { key: 'Enter', shiftKey: true })
    expect(fetch).toHaveBeenCalledTimes(2)

    await textarea.setValue('回车发送')
    await textarea.trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(wrapper.text()).toContain('收到')
    expect(fetch).toHaveBeenCalledTimes(3)
  })

  it('collapses and expands the sidebar', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))

    const wrapper = mount(App)

    expect(wrapper.text()).toContain("Shane's Site")
    await wrapper.get('button[aria-label="收起侧边栏"]').trigger('click')

    expect(wrapper.text()).not.toContain("Shane's Site")
    expect(wrapper.text()).toContain('S')
    expect(wrapper.get('button[aria-label="首页"]').exists()).toBe(true)
    expect(wrapper.get('button[aria-label="AI 问答"]').exists()).toBe(true)
    expect(wrapper.get('button[aria-label="文档库"]').exists()).toBe(true)
    await wrapper.get('button[aria-label="展开侧边栏"]').trigger('click')

    expect(wrapper.text()).toContain("Shane's Site")
    expect(wrapper.get('nav[aria-label="站点菜单"]').text()).toContain('AI 问答')
  })

  it('keeps one successful service visible when the other service fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse({ data: { service: 'java-api', language: 'Java', status: 'UP' } }))
        .mockRejectedValueOnce(new Error('Python API unavailable')),
    )

    const wrapper = mount(App)
    await flushPromises()

    expect(wrapper.text()).toContain('java-api')
    expect(wrapper.text()).toContain('Python API unavailable')
    expect(wrapper.text()).toContain('连接失败')
  })

  it('shows loading state before backend calls resolve', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))

    const wrapper = mount(App)

    expect(wrapper.text()).toContain('加载中')
    expect(wrapper.text()).toContain('正在读取服务状态')
  })
})
