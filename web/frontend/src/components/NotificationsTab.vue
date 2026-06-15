<template>
  <div id="tab-notifications" class="tab-panel" :class="{ active }">
    <div class="notif-section">
      <div class="notif-toolbar">
        <h2 class="scheduler-card-title">알림</h2>
        <div style="display:flex;gap:0.5rem">
          <button class="btn-secondary" @click="readAll">모두 읽음</button>
          <button class="btn-secondary btn-danger-soft" @click="clearAllAction">전체 삭제</button>
        </div>
      </div>

      <div class="notif-list">
        <div v-if="!notifs.length" class="empty-msg">알림이 없습니다.</div>
        <div
          v-for="n in notifs"
          :key="n.id"
          :class="['notif-card', `type-${n.type}`, { unread: !n.read }]"
          @click="markReadAction(n)"
        >
          <span :class="['notif-type-badge', `type-${n.type}`]">{{ TYPE_LABELS[n.type] || n.type }}</span>
          <div class="notif-body">
            <div class="notif-title">{{ n.title }}</div>
            <div class="notif-desc">{{ n.body }}</div>
            <div class="notif-time">{{ n.created_at }}</div>
            <button
              v-if="hasPreview(n)"
              class="notif-preview-btn"
              @click.stop="togglePreview(n)"
            >{{ openPreviews.has(n.id) ? '▲ 접기' : '▼ 미리보기' }}</button>
            <div v-if="openPreviews.has(n.id) && n.preview" class="notif-preview">
              <div v-if="n.preview.rows" class="notif-preview-rows">
                <div v-for="r in n.preview.rows" :key="r.label" class="notif-preview-row">
                  <span class="notif-preview-label">{{ r.label }}</span>
                  <span class="notif-preview-value">{{ r.value }}</span>
                </div>
              </div>
              <div v-if="n.preview.items" class="notif-preview-cases">
                <div v-for="(item, i) in n.preview.items" :key="i" class="notif-preview-case">
                  <div class="notif-case-name">{{ item.name }}</div>
                  <div class="notif-case-meta">{{ item.no }} · {{ item.court }} · {{ item.date }}</div>
                </div>
              </div>
            </div>
          </div>
          <button class="notif-delete-btn" @click.stop="deleteAction(n)">✕</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { getNotifications, markRead, markAllRead, deleteNotif, clearAll } from '../api/notifications.js'

const props = defineProps({ active: Boolean })
const emit  = defineEmits(['badge-update'])

const TYPE_LABELS = { 개정: '개정', 신규: '신규', 판례: '판례', 실패: '실패' }

const notifs       = ref([])
const openPreviews = ref(new Set())

const hasPreview = (n) => n.preview && (n.preview.rows?.length || n.preview.items?.length)

function togglePreview(n) {
  const s = new Set(openPreviews.value)
  if (s.has(n.id)) s.delete(n.id)
  else s.add(n.id)
  openPreviews.value = s
}

async function load() {
  try {
    const data = await getNotifications()
    notifs.value = data.notifications || []
    emit('badge-update', notifs.value.filter(n => !n.read).length)
  } catch {}
}

async function markReadAction(n) {
  if (n.read) return
  await markRead(n.id).catch(() => {})
  n.read = true
  emit('badge-update', notifs.value.filter(n => !n.read).length)
}

async function readAll() {
  await markAllRead().catch(() => {})
  notifs.value.forEach(n => n.read = true)
  emit('badge-update', 0)
}

async function deleteAction(n) {
  await deleteNotif(n.id).catch(() => {})
  notifs.value = notifs.value.filter(x => x.id !== n.id)
  emit('badge-update', notifs.value.filter(n => !n.read).length)
}

async function clearAllAction() {
  if (!confirm('알림을 모두 삭제하시겠습니까?')) return
  await clearAll().catch(() => {})
  notifs.value = []
  emit('badge-update', 0)
}

watch(() => props.active, (v) => { if (v) load() })
onMounted(load)

defineExpose({ load })
</script>
