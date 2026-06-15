<template>
  <div class="app">
    <header class="header">
      <div class="header-inner">
        <span class="header-icon">⚖</span>
        <h1>법령 서비스</h1>
      </div>
    </header>

    <nav class="tabs">
      <button
        v-for="tab in TABS"
        :key="tab.id"
        :class="['tab', { active: activeTab === tab.id }]"
        @click="switchTab(tab.id)"
      >
        {{ tab.label }}
        <span v-if="tab.id === 'notifications' && unreadCount > 0" class="tab-badge">
          {{ unreadCount > 99 ? '99+' : unreadCount }}
        </span>
      </button>
    </nav>

    <SearchTab       :active="activeTab === 'search'" />
    <PrecTab         :active="activeTab === 'prec'" />
    <ChatTab         :active="activeTab === 'chat'" />
    <SchedulerTab    :active="activeTab === 'scheduler'" />
    <UnifiedTab      :active="activeTab === 'unified'" />
    <NotificationsTab
      :active="activeTab === 'notifications'"
      ref="notifTab"
      @badge-update="unreadCount = $event"
    />

  </div>
  <ArticlePanel ref="articlePanel" />
</template>

<script setup>
import { ref, provide, onMounted } from 'vue'
import SearchTab        from './components/SearchTab.vue'
import PrecTab          from './components/PrecTab.vue'
import ChatTab          from './components/ChatTab.vue'
import SchedulerTab     from './components/SchedulerTab.vue'
import UnifiedTab       from './components/UnifiedTab.vue'
import NotificationsTab from './components/NotificationsTab.vue'
import ArticlePanel     from './components/ArticlePanel.vue'

const TABS = [
  { id: 'search',        label: '법령 검색' },
  { id: 'prec',          label: '판례 검색' },
  { id: 'chat',          label: '법령 상담' },
  { id: 'scheduler',     label: '수집 관리' },
  { id: 'unified',       label: '통합 검색' },
  { id: 'notifications', label: '알림' },
]

const activeTab   = ref('search')
const unreadCount = ref(0)

function switchTab(id) {
  activeTab.value = id
  window.scrollTo(0, 0)
}
const articlePanel = ref(null)
const notifTab     = ref(null)

function openArticle(lawName, joNum, joSub = 0) {
  articlePanel.value?.openPanel(lawName, joNum, joSub)
}

provide('openArticle', openArticle)

onMounted(() => {
  notifTab.value?.load()
})
</script>
