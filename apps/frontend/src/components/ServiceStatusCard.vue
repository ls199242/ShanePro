<script setup>
import { computed } from 'vue'

const props = defineProps({
  service: {
    type: Object,
    required: true,
  },
})

const statusLabel = computed(() => {
  if (props.service.state === 'success') {
    return '运行中'
  }

  if (props.service.state === 'error') {
    return '连接失败'
  }

  return '加载中'
})

const badgeClass = computed(() => {
  if (props.service.state === 'success') {
    return 'bg-[var(--success-bg)] text-[var(--success-text)] ring-[var(--success-bg)]'
  }

  if (props.service.state === 'error') {
    return 'bg-[var(--error-bg)] text-[var(--error-text)] ring-[var(--error-bg)]'
  }

  return 'bg-[var(--warning-bg)] text-[var(--warning-text)] ring-[var(--warning-bg)]'
})
</script>

<template>
  <article class="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-5 shadow-[var(--shadow)] backdrop-blur">
    <div class="flex items-start justify-between gap-4">
      <div>
        <h2 class="text-base font-semibold text-[var(--text)]">{{ service.title }}</h2>
        <p class="mt-1 text-sm text-[var(--text-muted)]">{{ service.description }}</p>
      </div>
      <span class="rounded-full px-2.5 py-1 text-xs font-semibold ring-1" :class="badgeClass">
        {{ statusLabel }}
      </span>
    </div>

    <dl v-if="service.state === 'success'" class="mt-5 grid gap-3 text-sm text-[var(--text-muted)]">
      <div class="flex justify-between gap-4">
        <dt class="text-[var(--text-subtle)]">服务</dt>
        <dd class="font-medium text-[var(--text)]">{{ service.data.service }}</dd>
      </div>
      <div class="flex justify-between gap-4">
        <dt class="text-[var(--text-subtle)]">语言</dt>
        <dd class="font-medium text-[var(--text)]">{{ service.data.language }}</dd>
      </div>
      <div class="flex justify-between gap-4">
        <dt class="text-[var(--text-subtle)]">状态</dt>
        <dd class="font-medium text-[var(--text)]">{{ service.data.status }}</dd>
      </div>
    </dl>

    <p v-else-if="service.state === 'error'" class="mt-5 rounded-md bg-[var(--error-bg)] px-3 py-2 text-sm text-[var(--error-text)]">
      {{ service.error }}
    </p>

    <p v-else class="mt-5 rounded-md bg-[var(--surface-muted)] px-3 py-2 text-sm text-[var(--warning-text)]">
      正在读取服务状态...
    </p>
  </article>
</template>
