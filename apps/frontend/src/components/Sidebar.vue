<script setup>
import { ref } from 'vue'

defineProps({
  items: {
    type: Array,
    required: true,
  },
})

defineEmits(['select'])

const collapsed = ref(false)
</script>

<template>
  <aside
    class="min-h-screen shrink-0 border-r border-[var(--sidebar-border)] bg-[var(--sidebar-bg)] px-4 py-6 shadow-[var(--sidebar-shadow)] transition-[width] duration-200"
    :class="collapsed ? 'w-20' : 'w-64'"
  >
    <div
      class="flex items-center gap-3"
      :class="collapsed ? 'justify-center gap-2' : 'justify-between'"
    >
      <h1 v-if="!collapsed" class="text-xl font-bold tracking-tight text-[var(--sidebar-text)]">Shane's Site</h1>
      <div
        v-else
        class="grid h-8 w-8 place-items-center rounded-md border border-[var(--sidebar-active-ring)] bg-[var(--sidebar-active-bg)] text-base font-bold text-[var(--sidebar-text)]"
        aria-label="Shane's Site"
      >
        S
      </div>

      <button
        type="button"
        class="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-[var(--sidebar-active-ring)] bg-[var(--sidebar-active-bg)] text-sm font-semibold text-[var(--sidebar-text)] hover:opacity-85"
        :aria-label="collapsed ? '展开侧边栏' : '收起侧边栏'"
        @click="collapsed = !collapsed"
      >
        {{ collapsed ? '>' : '<' }}
      </button>
    </div>

    <nav aria-label="站点菜单" class="mt-8 space-y-2">
      <button
        v-for="item in items"
        :key="item.key"
        type="button"
        class="group relative flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm font-medium"
        :class="[
          item.active ? 'bg-[var(--sidebar-active-bg)] text-[var(--sidebar-text)] ring-1 ring-[var(--sidebar-active-ring)]' : 'text-[var(--sidebar-muted)] hover:bg-[var(--sidebar-icon-muted-bg)] hover:text-[var(--sidebar-text)]',
          collapsed ? 'justify-center' : '',
        ]"
        :aria-label="item.label"
        :title="collapsed ? item.label : undefined"
        @click="$emit('select', item.key)"
      >
        <span class="grid h-6 min-w-6 place-items-center rounded-md text-xs font-bold" :class="item.active ? 'bg-[var(--sidebar-icon-bg)] text-[var(--sidebar-text)]' : 'bg-[var(--sidebar-icon-muted-bg)] text-[var(--sidebar-icon-muted)]'">
          {{ item.icon }}
        </span>
        <span v-if="!collapsed">{{ item.label }}</span>
        <span
          v-if="collapsed"
          class="pointer-events-none absolute left-[calc(100%+10px)] top-1/2 z-20 -translate-y-1/2 whitespace-nowrap rounded-md border border-[var(--border)] bg-[var(--surface-strong)] px-2.5 py-1.5 text-xs font-medium text-[var(--text)] opacity-0 shadow-[var(--shadow-soft)] transition-opacity group-hover:opacity-100"
        >
          {{ item.label }}
        </span>
      </button>
    </nav>
  </aside>
</template>
