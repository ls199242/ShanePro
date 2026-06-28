export const serviceConfigs = [
  {
    key: 'java',
    title: 'Java API',
    endpoint: '/java-api/api/site',
    description: 'Spring Boot service',
  },
  {
    key: 'python',
    title: 'Python API',
    endpoint: '/python-api/api/site',
    description: 'FastAPI service',
  },
]

async function requestJson(endpoint) {
  const response = await fetch(endpoint)

  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`)
  }

  return response.json()
}

async function postJson(endpoint, payload) {
  const response = await fetch(endpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`
    try {
      const errorBody = await response.json()
      detail = errorBody.detail || detail
    } catch {
      // Ignore non-JSON error responses and keep the status message.
    }
    throw new Error(detail)
  }

  const body = await response.json()
  if (body.code && body.code !== 0) {
    throw new Error(body.message || 'AI request failed')
  }

  return body.data ?? body
}

async function requestApiData(endpoint, options = {}) {
  const response = await fetch(endpoint, options)

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`
    try {
      const errorBody = await response.json()
      detail = errorBody.detail || errorBody.message || detail
    } catch {
      // Ignore non-JSON error responses and keep the status message.
    }
    throw new Error(detail)
  }

  const body = await response.json()
  if (body.code && body.code !== 0) {
    throw new Error(body.message || 'Request failed')
  }
  return body.data ?? body
}

export async function fetchServiceStatuses(configs = serviceConfigs) {
  return Promise.all(
    configs.map(async (config) => {
      try {
        const response = await requestJson(config.endpoint)

        return {
          ...config,
          state: 'success',
          data: response.data ?? response,
          error: '',
        }
      } catch (error) {
        return {
          ...config,
          state: 'error',
          data: null,
          error: error instanceof Error ? error.message : 'Unknown error',
        }
      }
    }),
  )
}

/**
 * 发送非流式 AI 对话请求。
 * @param {Object} params - 请求参数。
 * @param {string} params.message - 用户输入内容。
 * @param {string} [params.sessionId] - 后端会话 ID。
 * @param {boolean} [params.webSearchEnabled=true] - 是否允许本轮使用联网搜索。
 * @param {boolean} [params.ragEnabled=true] - 是否允许本轮使用个人文档 RAG。
 * @returns {Promise<Object>} AI 对话响应。
 */
export async function sendChatMessage({ message, sessionId, webSearchEnabled = true, ragEnabled = true }) {
  return postJson('/python-api/api/chat', {
    message,
    session_id: sessionId || null,
    web_search_enabled: webSearchEnabled,
    rag_enabled: ragEnabled,
  })
}

/**
 * 查询已上传的个人文档列表。
 * @returns {Promise<Array>} 文档摘要列表。
 */
export async function fetchDocuments() {
  return requestApiData('/python-api/api/documents')
}

/**
 * 上传个人文档并保存后端元数据。
 * @param {File} file - 待上传的 txt、md 或 pdf 文件。
 * @returns {Promise<Object>} 文档上传结果。
 */
export async function uploadDocument(file) {
  const formData = new FormData()
  formData.append('file', file)
  return requestApiData('/python-api/api/documents/upload', {
    method: 'POST',
    body: formData,
  })
}

/**
 * 触发个人文档解析、切分和向量化。
 * @param {string} documentId - 文档 ID。
 * @returns {Promise<Object>} 当前文档处理状态。
 */
export async function processDocument(documentId) {
  return requestApiData(`/python-api/api/documents/${documentId}/process`, {
    method: 'POST',
  })
}

/**
 * 删除个人文档及对应向量。
 * @param {string} documentId - 文档 ID。
 * @returns {Promise<Object>} 删除结果。
 */
export async function deleteDocument(documentId) {
  return requestApiData(`/python-api/api/documents/${documentId}`, {
    method: 'DELETE',
  })
}

/**
 * 发送流式 AI 对话请求，并按 SSE 事件回调更新页面状态。
 * @param {Object} params - 请求参数。
 * @param {string} params.message - 用户输入内容。
 * @param {string} [params.sessionId] - 后端会话 ID。
 * @param {boolean} [params.webSearchEnabled=true] - 是否允许本轮使用联网搜索。
 * @param {boolean} [params.ragEnabled=true] - 是否允许本轮使用个人文档 RAG。
 * @param {Function} [params.onSession] - 收到 session 事件时调用。
 * @param {Function} [params.onAgentEvent] - 收到 LangChain agent 事件时调用。
 * @param {Function} [params.onDone] - 收到最终响应时调用。
 * @returns {Promise<void>} 流式读取完成后结束。
 */
export async function streamChatMessage({
  message,
  sessionId,
  webSearchEnabled = true,
  ragEnabled = true,
  onSession,
  onAgentEvent,
  onDone,
}) {
  const response = await fetch('/python-api/api/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      message,
      session_id: sessionId || null,
      web_search_enabled: webSearchEnabled,
      rag_enabled: ragEnabled,
    }),
  })

  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`)
  }

  if (!response.body) {
    throw new Error('Current browser does not support streaming responses')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) {
      break
    }

    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split('\n\n')
    buffer = frames.pop() || ''

    for (const frame of frames) {
      handleSseFrame(frame, { onSession, onAgentEvent, onDone })
    }
  }

  if (buffer.trim()) {
    handleSseFrame(buffer, { onSession, onAgentEvent, onDone })
  }
}

function handleSseFrame(frame, handlers) {
  const lines = frame.split('\n')
  let event = 'message'
  const dataLines = []

  for (const line of lines) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    }
    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart())
    }
  }

  if (dataLines.length === 0) {
    return
  }

  const payload = JSON.parse(dataLines.join('\n'))
  if (event === 'session') {
    handlers.onSession?.(payload)
    return
  }
  if (event === 'agent_done') {
    handlers.onDone?.(payload)
    return
  }
  if (event.startsWith('on_')) {
    handlers.onAgentEvent?.({ event, ...payload })
    return
  }
  if (event === 'error') {
    throw new Error(payload.message || 'AI stream failed')
  }
}
