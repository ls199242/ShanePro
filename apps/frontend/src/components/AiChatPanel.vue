<script setup>
import { computed, ref } from 'vue'
import { streamChatMessage } from '../api/services'

const input = ref('')
const loading = ref(false)
const error = ref('')
let sessionSeq = 0
let interactionSeq = 0

function createSession() {
  sessionSeq += 1
  return {
    id: `local-session-${sessionSeq}`,
    backendSessionId: '',
    title: '新对话',
    messages: [],
    interactions: [],
    webSearchEnabled: true,
    ragEnabled: true,
    createdAt: new Date().toLocaleString(),
    updatedAt: '',
  }
}

const firstSession = createSession()
const sessions = ref([firstSession])
const activeSessionId = ref(firstSession.id)

const activeSession = computed(() => sessions.value.find((session) => session.id === activeSessionId.value) || sessions.value[0])

function formatJson(value) {
  return JSON.stringify(value, null, 2)
}

function parseMessageText(content) {
  if (typeof content === 'string') {
    const trimmed = content.trim()
    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
      try {
        const parsed = JSON.parse(trimmed)
        const parsedText = parseMessageText(parsed)
        return parsedText || content
      } catch {
        return content
      }
    }
    return content
  }

  if (Array.isArray(content)) {
    return content.map((item) => parseMessageText(item)).join('')
  }

  if (content && typeof content === 'object') {
    return typeof content.text === 'string' ? content.text : ''
  }

  return ''
}

function parseJsonValue(value) {
  if (typeof value !== 'string') {
    return value
  }

  const trimmed = value.trim()
  if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) {
    return value
  }

  try {
    return JSON.parse(trimmed)
  } catch {
    return value
  }
}

function applyToolEvent(tools, payload) {
  const currentTools = Array.isArray(tools) ? [...tools] : []
  const toolName = payload.name || 'unknown'
  const runningIndex = currentTools.findLastIndex((tool) => tool.name === toolName && tool.status === 'running')
  const eventData = payload.data || {}

  if (payload.event === 'on_tool_start') {
    currentTools.push({
      name: toolName,
      status: 'running',
      input: eventData.input || {},
    })
    return currentTools
  }

  const output = parseJsonValue(eventData.output)
  const outputError = output && typeof output === 'object' && output.status === 'error' ? output.error : ''
  const nextTool = {
    name: toolName,
    status: payload.event === 'on_tool_error' || outputError ? 'error' : 'success',
    input: eventData.input || currentTools[runningIndex]?.input || {},
    output: outputError ? null : output,
    error: eventData.error || outputError || '',
  }
  if (runningIndex >= 0) {
    currentTools[runningIndex] = nextTool
    return currentTools
  }
  currentTools.push(nextTool)
  return currentTools
}

function extractAgentText(payload) {
  return parseMessageText(payload?.data?.text || '')
}

function extractAgentThinking(payload) {
  return parseMessageText(payload?.data?.thinking || '')
}

function normalizeDoneResponse(response, fallbackThinking, fallbackTools) {
  const thinking = parseMessageText(response?.thinking || fallbackThinking || '')
  const tools = Array.isArray(response?.tools) && response.tools.length > 0 ? response.tools : fallbackTools
  const history = Array.isArray(response?.history)
    ? response.history.map((message) => ({
        ...message,
        thinking: parseMessageText(message.thinking || ''),
      }))
    : []
  const lastAssistantIndex = history.map((message) => message.role).lastIndexOf('assistant')

  if (thinking && lastAssistantIndex >= 0 && !history[lastAssistantIndex].thinking) {
    history[lastAssistantIndex] = {
      ...history[lastAssistantIndex],
      thinking,
    }
  }

  return {
    ...response,
    thinking,
    tools,
    history,
  }
}

function toolDisplayName(name) {
  if (name === 'web_search') {
    return 'Web 搜索'
  }
  if (name === 'personal_knowledge_search') {
    return '个人知识库'
  }
  return name
}

function toolStatusText(status) {
  if (status === 'success') {
    return '完成'
  }
  if (status === 'error') {
    return '失败'
  }
  return '调用中'
}

function updateSession(sessionId, updater) {
  sessions.value = sessions.value.map((session) => (session.id === sessionId ? updater(session) : session))
}

function switchSession(sessionId) {
  activeSessionId.value = sessionId
  input.value = ''
  error.value = ''
}

function createNewSession() {
  const session = createSession()
  sessions.value = [session, ...sessions.value]
  activeSessionId.value = session.id
  input.value = ''
  error.value = ''
}

function isWebSearchEnabled(session) {
  return session?.webSearchEnabled !== false
}

function isRagEnabled(session) {
  return session?.ragEnabled !== false
}

function canModifyWebSearch(session) {
  return Boolean(
    session
      && !loading.value
      && !session.backendSessionId
      && session.messages.length === 0
      && session.interactions.length === 0,
  )
}

function canModifyRag(session) {
  return canModifyWebSearch(session)
}

function toggleWebSearch() {
  if (!canModifyWebSearch(activeSession.value)) {
    return
  }

  updateSession(activeSession.value.id, (session) => ({
    ...session,
    webSearchEnabled: !isWebSearchEnabled(session),
  }))
}

function toggleRag() {
  if (!canModifyRag(activeSession.value)) {
    return
  }

  updateSession(activeSession.value.id, (session) => ({
    ...session,
    ragEnabled: !isRagEnabled(session),
  }))
}

async function submitMessage() {
  const content = input.value.trim()
  const currentSession = activeSession.value
  if (!content || loading.value || !currentSession) {
    return
  }

  const webSearchEnabled = isWebSearchEnabled(currentSession)
  const ragEnabled = isRagEnabled(currentSession)
  const requestPayload = {
    message: content,
    session_id: currentSession.backendSessionId || null,
    web_search_enabled: webSearchEnabled,
    rag_enabled: ragEnabled,
  }
  const interactionId = `interaction-${interactionSeq}`
  interactionSeq += 1

  updateSession(currentSession.id, (session) => ({
    ...session,
    title: session.messages.length === 0 ? content.slice(0, 18) : session.title,
    messages: [
      ...session.messages,
      { role: 'user', content },
      { role: 'assistant', content: '', streamInteractionId: interactionId },
    ],
    interactions: [
      ...session.interactions,
      {
        id: interactionId,
        status: 'pending',
        request: requestPayload,
        response: {
          session_id: requestPayload.session_id,
          answer: '',
          thinking: '',
          tools: [],
          streaming: true,
        },
        error: '',
      },
    ],
    updatedAt: new Date().toLocaleString(),
  }))
  input.value = ''
  loading.value = true
  error.value = ''

  try {
    let streamAnswer = ''
    let streamThinking = ''
    let streamTools = []
    let streamSessionId = currentSession.backendSessionId

    await streamChatMessage({
      message: content,
      sessionId: currentSession.backendSessionId,
      webSearchEnabled,
      ragEnabled,
      onSession: (payload) => {
        streamSessionId = payload.session_id
        updateSession(currentSession.id, (session) => ({
          ...session,
          backendSessionId: streamSessionId,
          interactions: session.interactions.map((item) => item.id === interactionId
            ? {
                ...item,
                response: {
                  ...item.response,
                  session_id: streamSessionId,
                },
              }
            : item),
        }))
      },
      onAgentEvent: (payload) => {
        if (payload.event === 'on_tool_start' || payload.event === 'on_tool_end' || payload.event === 'on_tool_error') {
          streamTools = applyToolEvent(streamTools, payload)
          updateSession(currentSession.id, (session) => ({
            ...session,
            interactions: session.interactions.map((item) => item.id === interactionId
              ? {
                  ...item,
                  response: {
                    ...item.response,
                    tools: streamTools,
                  },
                }
              : item),
            updatedAt: new Date().toLocaleString(),
          }))
          return
        }

        if (payload.event !== 'on_chat_model_stream') {
          return
        }

        const text = extractAgentText(payload)
        const thinking = extractAgentThinking(payload)
        streamAnswer += text
        streamThinking += thinking
        updateSession(currentSession.id, (session) => ({
          ...session,
          messages: session.messages.map((message) => message.streamInteractionId === interactionId
            ? {
                ...message,
                content: streamAnswer,
                thinking: streamThinking,
              }
            : message),
          interactions: session.interactions.map((item) => item.id === interactionId
            ? {
                ...item,
                response: {
                  ...item.response,
                  session_id: streamSessionId || item.response?.session_id || null,
                  answer: streamAnswer,
                  thinking: streamThinking,
                  tools: streamTools,
                  streaming: true,
                },
              }
            : item),
          updatedAt: new Date().toLocaleString(),
        }))
      },
      onDone: (response) => {
        const normalizedResponse = normalizeDoneResponse(response, streamThinking, streamTools)
        updateSession(currentSession.id, (session) => ({
          ...session,
          backendSessionId: normalizedResponse.session_id,
          messages: normalizedResponse.history.length > 0 ? normalizedResponse.history : session.messages,
          interactions: session.interactions.map((item) => item.id === interactionId
            ? {
                ...item,
                status: 'success',
                response: normalizedResponse,
              }
            : item),
          updatedAt: new Date().toLocaleString(),
        }))
      },
    })
  } catch (err) {
    const errorMessage = err instanceof Error ? err.message : 'AI 问答请求失败'
    error.value = errorMessage
    updateSession(currentSession.id, (session) => ({
      ...session,
      messages: session.messages.map((message) => message.streamInteractionId === interactionId && !message.content
        ? {
            ...message,
            content: `请求失败：${errorMessage}`,
          }
        : message),
      interactions: session.interactions.map((item) => item.id === interactionId
        ? {
          ...item,
          status: 'error',
          error: errorMessage,
        }
        : item),
      updatedAt: new Date().toLocaleString(),
    }))
  } finally {
    loading.value = false
  }
}

function handleInputKeydown(event) {
  if (event.key !== 'Enter' || event.shiftKey) {
    return
  }

  event.preventDefault()
  submitMessage()
}
</script>

<template>
  <section class="relative" aria-label="AI 问答">
    <div class="mb-4 flex items-center justify-between gap-3">
      <div>
        <h1 class="text-base font-semibold text-[var(--text)]">当前对话</h1>
        <p class="mt-1 text-xs text-[var(--text-muted)]">{{ activeSession.backendSessionId || '尚未建立后端 session' }}</p>
      </div>
      <div class="flex flex-wrap items-center justify-end gap-2">
        <button
          type="button"
          class="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-semibold shadow-[var(--shadow-soft)] hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          :class="isWebSearchEnabled(activeSession)
            ? 'border-[var(--button-border)] bg-[var(--accent-soft)] text-[var(--text)]'
            : 'border-[var(--border-soft)] bg-[var(--surface)] text-[var(--text-muted)]'"
          :aria-label="isWebSearchEnabled(activeSession) ? '关闭联网搜索' : '开启联网搜索'"
          :disabled="!canModifyWebSearch(activeSession)"
          :title="canModifyWebSearch(activeSession) ? '设置新对话是否允许联网搜索' : '当前对话已开始，新建对话后可修改联网搜索'"
          @click="toggleWebSearch"
        >
          <span aria-hidden="true">⌕</span>
          <span>联网搜索 {{ isWebSearchEnabled(activeSession) ? '开' : '关' }}</span>
        </button>
        <button
          type="button"
          class="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-semibold shadow-[var(--shadow-soft)] hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          :class="isRagEnabled(activeSession)
            ? 'border-[var(--button-border)] bg-[var(--accent-soft)] text-[var(--text)]'
            : 'border-[var(--border-soft)] bg-[var(--surface)] text-[var(--text-muted)]'"
          :aria-label="isRagEnabled(activeSession) ? '关闭个人文档 RAG' : '开启个人文档 RAG'"
          :disabled="!canModifyRag(activeSession)"
          :title="canModifyRag(activeSession) ? '设置新对话是否允许使用个人文档 RAG' : '当前对话已开始，新建对话后可修改个人文档 RAG'"
          @click="toggleRag"
        >
          <span aria-hidden="true">文</span>
          <span>个人文档 RAG {{ isRagEnabled(activeSession) ? '开' : '关' }}</span>
        </button>
        <button
          type="button"
          class="rounded-md border border-[var(--button-border)] bg-[var(--button-bg)] px-3 py-1.5 text-xs font-semibold text-[var(--button-text)] shadow-[var(--shadow-soft)] hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="loading"
          @click="createNewSession"
        >
          新建对话
        </button>
      </div>
    </div>

    <div class="h-[340px] overflow-auto rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 shadow-[var(--shadow)] backdrop-blur">
      <div
        v-if="activeSession.messages.length === 0"
        class="flex h-full items-center justify-center rounded-md border border-dashed border-[var(--border-soft)] bg-[var(--surface-soft)] px-4 text-sm text-[var(--warning-text)]"
      >
        输入问题后开始会话
      </div>

      <div v-else class="space-y-3">
        <div
          v-for="(message, index) in activeSession.messages"
          :key="`${message.role}-${index}`"
          class="flex"
          :class="message.role === 'user' ? 'justify-end' : 'justify-start'"
        >
          <div
            class="max-w-[78%] rounded-lg px-4 py-3 text-sm leading-6"
            :class="message.role === 'user'
              ? 'bg-[var(--accent)] text-[var(--code-text)] shadow-[var(--shadow-soft)]'
              : 'bg-[var(--surface-muted)] text-[var(--text)] ring-1 ring-[var(--border-soft)]'"
          >
            <div
              v-if="message.role === 'assistant' && parseMessageText(message.thinking)"
              class="mb-2 rounded-md border border-[var(--border-soft)] bg-[var(--surface-soft)] px-2.5 py-2 text-xs leading-5 text-[var(--text-muted)]"
            >
              <span class="mb-1 block text-[10px] font-semibold text-[var(--warning-text)]">思考过程</span>
              <span class="whitespace-pre-wrap">{{ parseMessageText(message.thinking) }}</span>
            </div>
            <div class="whitespace-pre-wrap">
              {{ parseMessageText(message.content) || (parseMessageText(message.thinking) ? '正在整理回复...' : '') }}
            </div>
          </div>
        </div>
      </div>
    </div>

    <form class="mt-4 flex items-stretch gap-3" @submit.prevent="submitMessage">
      <textarea
        v-model="input"
        class="box-border h-10 min-h-10 flex-1 resize-none overflow-hidden rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-[8px] text-sm leading-[22px] text-[var(--text)] outline-none placeholder:text-[var(--text-subtle)] focus:border-[var(--accent)]"
        placeholder="输入你的问题"
        rows="1"
        @keydown="handleInputKeydown"
      />
      <button
        type="submit"
        class="box-border flex h-10 min-h-10 items-center justify-center rounded-md border border-[var(--button-border)] bg-[var(--accent)] px-4 text-sm font-semibold leading-none text-[var(--code-text)] shadow-[0_12px_28px_rgba(93,62,39,0.16)] hover:bg-[var(--accent-hover)] disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="loading || !input.trim()"
      >
        {{ loading ? '发送中' : '发送' }}
      </button>
    </form>

    <p v-if="error" class="mt-4 rounded-md bg-[var(--error-bg)] px-3 py-2 text-sm text-[var(--error-text)]">
      {{ error }}
    </p>

    <div class="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(320px,0.95fr)]">
      <article class="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 shadow-[var(--shadow-soft)]">
        <h2 class="text-sm font-semibold text-[var(--text)]">历史 Session</h2>
        <div class="mt-4 min-h-[260px] space-y-2">
          <div
            v-if="sessions.length === 0"
            class="flex min-h-[220px] items-center justify-center rounded-md border border-dashed border-[var(--border-soft)] bg-[var(--surface-soft)] px-4 text-sm text-[var(--warning-text)]"
          >
            暂无历史会话
          </div>

          <button
            v-for="session in sessions"
            :key="session.id"
            type="button"
            class="w-full rounded-md border px-3 py-2 text-left"
            :class="session.id === activeSession.id ? 'border-[var(--button-border)] bg-[var(--accent-soft)] text-[var(--text)]' : 'border-[var(--border-soft)] bg-[var(--surface)] text-[var(--warning-text)] hover:bg-[var(--surface-strong)]'"
            @click="switchSession(session.id)"
          >
            <span class="block truncate text-sm font-semibold">{{ session.title }}</span>
            <span class="mt-1 block truncate text-xs opacity-70">
              {{ session.backendSessionId || '本地新会话' }}
            </span>
          </button>
        </div>
      </article>

      <article class="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 shadow-[var(--shadow-soft)]">
        <h2 class="text-sm font-semibold text-[var(--text)]">交互记录</h2>
        <div
          v-if="activeSession.interactions.length === 0"
          class="mt-4 flex min-h-[260px] items-center justify-center rounded-md border border-dashed border-[var(--border-soft)] bg-[var(--surface-soft)] px-4 text-sm text-[var(--warning-text)]"
        >
          发送后展示每一轮入参和出参
        </div>

        <div v-else class="mt-4 max-h-[420px] space-y-4 overflow-auto pr-1">
          <div
            v-for="(interaction, index) in activeSession.interactions"
            :key="interaction.id"
            class="rounded-md border border-[var(--border-soft)] bg-[var(--surface-alt)] p-3"
          >
            <div class="mb-3 flex items-center justify-between gap-3">
              <span class="text-xs font-semibold text-[var(--text-muted)]">第 {{ index + 1 }} 轮</span>
              <span class="rounded-full px-2 py-0.5 text-[11px] font-semibold" :class="interaction.status === 'success' ? 'bg-[var(--success-bg)] text-[var(--success-text)]' : interaction.status === 'error' ? 'bg-[var(--error-bg)] text-[var(--error-text)]' : 'bg-[var(--warning-bg)] text-[var(--warning-text)]'">
                {{ interaction.status === 'success' ? '完成' : interaction.status === 'error' ? '失败' : '请求中' }}
              </span>
            </div>

            <p class="mb-1 text-xs font-semibold text-[var(--warning-text)]">入参</p>
            <pre class="overflow-auto rounded-md bg-[var(--code-bg)] p-3 text-xs leading-5 text-[var(--code-text)]">{{ formatJson(interaction.request) }}</pre>

            <template v-if="interaction.response?.tools?.length">
              <p class="mb-1 mt-3 text-xs font-semibold text-[var(--warning-text)]">工具调用</p>
              <div class="space-y-2">
                <div
                  v-for="(tool, toolIndex) in interaction.response.tools"
                  :key="`${interaction.id}-tool-${toolIndex}`"
                  class="rounded-md border border-[var(--border-soft)] bg-[var(--surface-soft)] p-3"
                >
                  <div class="mb-2 flex items-center justify-between gap-3">
                    <span class="text-xs font-semibold text-[var(--text)]">{{ toolDisplayName(tool.name) }}</span>
                    <span class="rounded-full px-2 py-0.5 text-[11px] font-semibold" :class="tool.status === 'success' ? 'bg-[var(--success-bg)] text-[var(--success-text)]' : tool.status === 'error' ? 'bg-[var(--error-bg)] text-[var(--error-text)]' : 'bg-[var(--warning-bg)] text-[var(--warning-text)]'">
                      {{ toolStatusText(tool.status) }}
                    </span>
                  </div>
                  <p class="mb-1 text-[11px] font-semibold text-[var(--warning-text)]">工具入参</p>
                  <pre class="overflow-auto rounded-md bg-[var(--code-bg)] p-2 text-xs leading-5 text-[var(--code-text)]">{{ formatJson(tool.input || {}) }}</pre>
                  <template v-if="tool.output">
                    <p class="mb-1 mt-2 text-[11px] font-semibold text-[var(--warning-text)]">工具出参</p>
                    <pre class="overflow-auto rounded-md bg-[var(--code-bg)] p-2 text-xs leading-5 text-[var(--code-text)]">{{ formatJson(tool.output) }}</pre>
                  </template>
                  <p v-if="tool.error" class="mt-2 rounded-md bg-[var(--error-bg)] px-2 py-1.5 text-xs text-[var(--error-text)]">
                    {{ tool.error }}
                  </p>
                </div>
              </div>
            </template>

            <template v-if="parseMessageText(interaction.response?.thinking)">
              <p class="mb-1 mt-3 text-xs font-semibold text-[var(--warning-text)]">思考过程</p>
              <pre class="overflow-auto rounded-md bg-[var(--surface-soft)] p-3 text-xs leading-5 text-[var(--text-muted)]">{{ parseMessageText(interaction.response.thinking) }}</pre>
            </template>

            <p class="mb-1 mt-3 text-xs font-semibold text-[var(--warning-text)]">出参</p>
            <pre class="overflow-auto rounded-md bg-[var(--code-bg)] p-3 text-xs leading-5 text-[var(--code-text)]">{{ formatJson(interaction.error ? { error: interaction.error } : interaction.response || { pending: true }) }}</pre>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>
