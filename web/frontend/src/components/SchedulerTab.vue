<template>
  <div id="tab-scheduler" class="tab-panel" :class="{ active }">
    <div class="scheduler-section">

      <!-- 법령 목록 -->
      <div class="scheduler-card">
        <div class="scheduler-card-header">
          <h2 class="scheduler-card-title">수집 대상 법령</h2>
          <div style="display:flex;gap:0.5rem">
            <button class="btn-secondary" @click="openPreset">추천 법령</button>
            <button class="btn-add" @click="openAdd">+ 직접 추가</button>
          </div>
        </div>
        <table class="scheduler-table">
          <thead>
            <tr><th>법령명</th><th>수집 주기</th><th>마지막 수집</th><th>다음 수집 예정</th><th>상태</th><th>액션</th></tr>
          </thead>
          <tbody>
            <tr v-if="lawsState === 'loading'"><td colspan="6" class="empty-msg">불러오는 중...</td></tr>
            <tr v-else-if="!laws.length"><td colspan="6" class="empty-msg">등록된 법령이 없습니다.</td></tr>
            <tr v-for="law in laws" :key="law.id">
              <td>{{ law.name }}</td>
              <td>{{ fmtScheduleInterval(law.interval, law.day, law.time) }}</td>
              <td>{{ law.last_run || '-' }}</td>
              <td>{{ law.next_run || '-' }}</td>
              <td><span :class="['status-badge', `status-${law.status || 'idle'}`]">{{ STATUS_LABEL[law.status] || law.status }}</span></td>
              <td>
                <button class="btn-run"    @click="runLawAction(law)">수집</button>
                <button class="btn-edit"   @click="openEdit(law)">편집</button>
                <button class="btn-delete" @click="deleteLawAction(law)">삭제</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 수집 이력 -->
      <div class="scheduler-card">
        <div class="scheduler-card-header">
          <h2 class="scheduler-card-title">수집 이력</h2>
          <button class="btn-secondary" @click="loadLogs">새로고침</button>
        </div>
        <table class="scheduler-table">
          <thead>
            <tr><th>실행 시각</th><th>법령명</th><th>결과</th><th>수집 건수</th><th>메시지</th></tr>
          </thead>
          <tbody>
            <tr v-if="!logs.length"><td colspan="5" class="empty-msg">이력이 없습니다.</td></tr>
            <tr v-for="log in logs" :key="log.id">
              <td>{{ log.started_at }}</td>
              <td>{{ log.law_name }}</td>
              <td><span :class="['status-badge', `status-${log.status}`]">{{ STATUS_LABEL[log.status] || log.status }}</span></td>
              <td>{{ log.count ?? '-' }}</td>
              <td>{{ log.message || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- 법령 추가/편집 모달 -->
  <LawModal
    v-if="modal.open"
    :editing-id="modal.id"
    :initial-name="modal.name"
    :initial-interval="modal.interval"
    :initial-day="modal.day"
    :initial-time="modal.time"
    @close="modal.open = false"
    @saved="onSaved"
  />

  <!-- 추천 법령 모달 -->
  <PresetModal
    v-if="presetOpen"
    :presets="presets"
    :existing="existingNames"
    @close="presetOpen = false"
    @saved="onSaved"
  />
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { getLaws, runLaw, deleteLaw, getLogs, getPresets } from '../api/scheduler.js'
import { fmtScheduleInterval } from '../utils/format.js'
import LawModal from './LawModal.vue'
import PresetModal from './PresetModal.vue'

const props = defineProps({ active: Boolean })

const STATUS_LABEL = { idle: '대기', running: '수집중', success: '완료', failed: '실패' }

const laws      = ref([])
const logs      = ref([])
const presets   = ref([])
const lawsState = ref('loading')
const presetOpen = ref(false)
const modal     = ref({ open: false, id: null, name: '', interval: 'weekly', day: '월', time: '09:00' })

const existingNames = computed(() => new Set(laws.value.map(l => l.name)))

async function loadLaws() {
  lawsState.value = 'loading'
  try {
    const data = await getLaws()
    laws.value = data.laws || []
  } catch {}
  lawsState.value = 'done'
}

async function loadLogs() {
  try {
    const data = await getLogs()
    logs.value = data.logs || []
  } catch {}
}

async function openPreset() {
  if (!presets.value.length) {
    const data = await getPresets().catch(() => ({ presets: [] }))
    presets.value = data.presets || []
  }
  presetOpen.value = true
}

function openAdd() {
  modal.value = { open: true, id: null, name: '', interval: 'weekly', day: '월', time: '09:00' }
}

function openEdit(law) {
  modal.value = {
    open: true,
    id: law.id,
    name: law.name,
    interval: law.interval,
    day: law.day || '월',
    time: law.time || '09:00',
  }
}

async function runLawAction(law) {
  if (!confirm(`"${law.name}" 수집을 지금 실행하시겠습니까?`)) return
  law.status = 'running'
  try {
    await runLaw(law.id)
    await loadLaws()
    await loadLogs()
  } catch (e) {
    alert(`수집 실패: ${e.message}`)
    law.status = 'failed'
  }
}

async function deleteLawAction(law) {
  if (!confirm(`"${law.name}"을(를) 삭제하시겠습니까?`)) return
  try {
    await deleteLaw(law.id)
    await loadLaws()
  } catch (e) {
    alert(`삭제 실패: ${e.message}`)
  }
}

async function onSaved() {
  await loadLaws()
  await loadLogs()
}

watch(() => props.active, (v) => { if (v) { loadLaws(); loadLogs() } })
onMounted(() => { loadLaws(); loadLogs() })
</script>
