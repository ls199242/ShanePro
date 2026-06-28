<script setup>
import { onBeforeUnmount, ref } from 'vue'
import { deleteDocument, fetchDocuments, processDocument, uploadDocument } from '../api/services'

const documents = ref([])
const documentLoading = ref(false)
const uploadLoading = ref(false)
const processingDocumentId = ref('')
const documentError = ref('')
let refreshTimer = null

const processingStatuses = new Set(['parsing', 'parsed', 'chunking', 'chunked', 'vectorizing'])

function documentStatusText(document) {
  if (document.is_failed) {
    return '失败'
  }
  const statusTextMap = {
    uploaded: '待处理',
    parsing: '解析中',
    parsed: '已解析',
    chunking: '切分中',
    chunked: '已切分',
    vectorizing: '向量化中',
    ready: '已入库',
  }
  return statusTextMap[document.status] || '未知状态'
}

function canProcessDocument(document) {
  return document.status !== 'ready' && !isDocumentProcessing(document)
}

function isDocumentProcessing(document) {
  return !document.is_failed && processingStatuses.has(document.status)
}

function formatFileSize(sizeBytes) {
  if (!Number.isFinite(sizeBytes)) {
    return '-'
  }
  if (sizeBytes < 1024) {
    return `${sizeBytes} B`
  }
  if (sizeBytes < 1024 * 1024) {
    return `${(sizeBytes / 1024).toFixed(1)} KB`
  }
  return `${(sizeBytes / 1024 / 1024).toFixed(1)} MB`
}

async function loadDocuments() {
  documentLoading.value = true
  documentError.value = ''
  try {
    documents.value = await fetchDocuments()
    scheduleProcessingRefresh()
  } catch (err) {
    documentError.value = err instanceof Error ? err.message : '文档列表读取失败'
  } finally {
    documentLoading.value = false
  }
}

function scheduleProcessingRefresh() {
  if (refreshTimer) {
    clearTimeout(refreshTimer)
    refreshTimer = null
  }
  if (documents.value.some((document) => isDocumentProcessing(document))) {
    refreshTimer = window.setTimeout(() => {
      loadDocuments()
    }, 3000)
  }
}

async function handleDocumentUpload(event) {
  const file = event.target.files?.[0]
  if (!file || uploadLoading.value) {
    return
  }

  uploadLoading.value = true
  documentError.value = ''
  try {
    await uploadDocument(file)
    await loadDocuments()
  } catch (err) {
    documentError.value = err instanceof Error ? err.message : '文档上传失败'
  } finally {
    uploadLoading.value = false
    event.target.value = ''
  }
}

async function startDocumentProcessing(document) {
  if (!canProcessDocument(document) || processingDocumentId.value) {
    return
  }

  processingDocumentId.value = document.id
  documentError.value = ''
  try {
    await processDocument(document.id)
    await loadDocuments()
  } catch (err) {
    documentError.value = err instanceof Error ? err.message : '文档处理触发失败'
  } finally {
    processingDocumentId.value = ''
  }
}

async function removeDocument(document) {
  if (!window.confirm(`确认删除文档「${document.filename}」？`)) {
    return
  }

  documentLoading.value = true
  documentError.value = ''
  try {
    await deleteDocument(document.id)
    documents.value = documents.value.filter((item) => item.id !== document.id)
  } catch (err) {
    documentError.value = err instanceof Error ? err.message : '文档删除失败'
  } finally {
    documentLoading.value = false
  }
}

onBeforeUnmount(() => {
  if (refreshTimer) {
    clearTimeout(refreshTimer)
  }
})
</script>

<template>
  <article class="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 shadow-[var(--shadow-soft)]">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="text-sm font-semibold text-[var(--text)]">个人文档库</h2>
        <p class="mt-1 text-xs text-[var(--text-muted)]">支持 txt、md、pdf，上传后可手动处理入库。</p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <label class="inline-flex cursor-pointer items-center rounded-md border border-[var(--button-border)] bg-[var(--button-bg)] px-3 py-1.5 text-xs font-semibold text-[var(--button-text)] shadow-[var(--shadow-soft)] hover:opacity-90">
          <span>{{ uploadLoading ? '上传中' : '上传文档' }}</span>
          <input
            type="file"
            class="sr-only"
            accept=".txt,.md,.pdf"
            :disabled="uploadLoading"
            @change="handleDocumentUpload"
          >
        </label>
        <button
          type="button"
          class="rounded-md border border-[var(--border-soft)] bg-[var(--surface)] px-3 py-1.5 text-xs font-semibold text-[var(--text)] shadow-[var(--shadow-soft)] hover:bg-[var(--surface-strong)] disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="documentLoading"
          @click="loadDocuments"
        >
          {{ documentLoading ? '刷新中' : '刷新文档' }}
        </button>
      </div>
    </div>

    <p v-if="documentError" class="mt-3 rounded-md bg-[var(--error-bg)] px-3 py-2 text-xs text-[var(--error-text)]">
      {{ documentError }}
    </p>

    <div v-if="documents.length" class="mt-3 grid gap-2 md:grid-cols-2">
      <div
        v-for="document in documents"
        :key="document.id"
        class="rounded-md border border-[var(--border-soft)] bg-[var(--surface-soft)] p-3"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="truncate text-sm font-semibold text-[var(--text)]">{{ document.filename }}</p>
            <p class="mt-1 text-xs text-[var(--text-muted)]">
              {{ formatFileSize(document.size_bytes) }} · {{ document.chunk_count }} chunks · {{ documentStatusText(document) }}
            </p>
            <p class="mt-1 truncate text-[11px] text-[var(--text-subtle)]">MD5 {{ document.md5 }}</p>
          </div>
          <div class="flex shrink-0 flex-col gap-1">
            <button
              v-if="canProcessDocument(document)"
              type="button"
              class="rounded-md border border-[var(--button-border)] bg-[var(--button-bg)] px-2 py-1 text-[11px] font-semibold text-[var(--button-text)] hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="documentLoading || Boolean(processingDocumentId)"
              @click="startDocumentProcessing(document)"
            >
              {{ processingDocumentId === document.id ? '触发中' : document.is_failed ? '重试处理' : '开始处理' }}
            </button>
            <button
              type="button"
              class="rounded-md border border-[var(--border-soft)] bg-[var(--surface)] px-2 py-1 text-[11px] font-semibold text-[var(--error-text)] hover:bg-[var(--surface-strong)] disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="documentLoading || Boolean(processingDocumentId)"
              @click="removeDocument(document)"
            >
              删除
            </button>
          </div>
        </div>
        <p v-if="document.error_message" class="mt-2 rounded-md bg-[var(--error-bg)] px-2 py-1.5 text-xs text-[var(--error-text)]">
          {{ document.error_message }}
        </p>
      </div>
    </div>
  </article>
</template>
