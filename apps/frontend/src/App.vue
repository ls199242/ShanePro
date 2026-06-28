<script setup>
import { onMounted, ref } from 'vue'
import { fetchServiceStatuses, serviceConfigs } from './api/services'
import AiChatPanel from './components/AiChatPanel.vue'
import DocumentLibraryPanel from './components/DocumentLibraryPanel.vue'
import ServiceStatusCard from './components/ServiceStatusCard.vue'
import Sidebar from './components/Sidebar.vue'

const menuItems = [
  {
    key: 'home',
    label: '首页',
    icon: '⌂',
    active: true,
  },
  {
    key: 'ai-chat',
    label: 'AI 问答',
    icon: 'AI',
    active: false,
  },
  {
    key: 'documents',
    label: '文档库',
    icon: '文',
    active: false,
  },
]

const activeMenu = ref('home')
const theme = ref('warm')
const services = ref(
  serviceConfigs.map((config) => ({
    ...config,
    state: 'loading',
    data: null,
    error: '',
  })),
)

async function loadServices() {
  services.value = serviceConfigs.map((config) => ({
    ...config,
    state: 'loading',
    data: null,
    error: '',
  }))
  services.value = await fetchServiceStatuses()
}

onMounted(loadServices)
</script>

<template>
  <div class="min-h-screen bg-[var(--page-bg)] text-[var(--page-text)] md:flex" :data-theme="theme === 'clean' ? 'clean' : undefined">
    <Sidebar
      :items="menuItems.map((item) => ({ ...item, active: item.key === activeMenu }))"
      @select="activeMenu = $event"
    />

    <main class="relative flex-1 overflow-auto px-5 py-6 sm:px-8 lg:px-10">
      <div class="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_14%_12%,var(--glow-a),transparent_28%),radial-gradient(circle_at_84%_10%,var(--glow-b),transparent_24%),linear-gradient(var(--grid-color)_1px,transparent_1px),linear-gradient(90deg,var(--grid-color)_1px,transparent_1px)] bg-[size:auto,auto,44px_44px,44px_44px]" />
      <div v-if="activeMenu === 'home'" class="relative mx-auto mb-5 flex max-w-6xl justify-end gap-2">
        <button
          type="button"
          class="grid h-8 w-8 place-items-center rounded-md border border-[var(--button-border)] bg-[var(--button-bg)] text-sm font-semibold text-[var(--button-text)] shadow-[var(--shadow-soft)] hover:opacity-90"
          :aria-label="theme === 'warm' ? '切换 C 清爽浅色' : '切换 A 暖色书房'"
          :title="theme === 'warm' ? '切换 C 清爽浅色' : '切换 A 暖色书房'"
          @click="theme = theme === 'warm' ? 'clean' : 'warm'"
        >
          {{ theme === 'warm' ? '☾' : '☀' }}
        </button>
        <button
          type="button"
          class="rounded-md border border-[var(--button-border)] bg-[var(--button-bg)] px-3 py-1.5 text-xs font-semibold text-[var(--button-text)] shadow-[var(--shadow-soft)] hover:opacity-90"
          @click="loadServices"
        >
          刷新状态
        </button>
      </div>

      <section v-if="activeMenu === 'home'" class="relative mx-auto grid max-w-6xl gap-4 lg:grid-cols-2" aria-label="后端服务状态">
        <ServiceStatusCard v-for="service in services" :key="service.key" :service="service" />
      </section>

      <AiChatPanel v-else-if="activeMenu === 'ai-chat'" class="relative mx-auto max-w-7xl" />

      <DocumentLibraryPanel v-else-if="activeMenu === 'documents'" class="relative mx-auto max-w-6xl" />
    </main>
  </div>
</template>
