<template>
  <div class="modal-overlay" style="display:flex" @click.self="emit('close')">
    <div class="modal">
      <div class="modal-header">
        <h3>{{ editingId ? '법령 편집' : '법령 추가' }}</h3>
        <button class="modal-close" @click="emit('close')">✕</button>
      </div>
      <div class="modal-body">
        <label class="modal-label">법령명</label>
        <div class="autocomplete-wrap">
          <input
            v-model="name"
            type="text"
            class="modal-input"
            placeholder="법령명 검색..."
            autocomplete="off"
            @input="onNameInput"
            @focus="onNameInput"
          />
          <ul v-if="suggestions.length" class="autocomplete-dropdown">
            <li
              v-for="s in suggestions"
              :key="s"
              class="autocomplete-item"
              @click="name = s; suggestions = []"
            >{{ s }}</li>
          </ul>
        </div>

        <label class="modal-label">수집 주기</label>
        <select v-model="interval" class="modal-input" @change="onIntervalChange">
          <option value="daily">매일</option>
          <option value="weekly">매주</option>
          <option value="monthly">매월</option>
        </select>

        <template v-if="interval === 'weekly'">
          <label class="modal-label">요일 선택</label>
          <div class="weekday-picker">
            <button
              v-for="d in DAYS"
              :key="d"
              type="button"
              :class="['weekday-btn', { active: day === d }]"
              @click="day = d"
            >{{ d }}</button>
          </div>
        </template>
        <template v-else-if="interval === 'monthly'">
          <label class="modal-label">날짜 선택</label>
          <select v-model="day" class="modal-input">
            <option v-for="d in 28" :key="d" :value="String(d)">{{ d }}일</option>
          </select>
        </template>

        <label class="modal-label">실행 시각</label>
        <div class="time-picker-row">
          <select v-model="hour" class="modal-input time-select">
            <option v-for="h in 24" :key="h-1" :value="pad(h-1)">{{ pad(h-1) }}시</option>
          </select>
          <span class="time-sep">:</span>
          <select v-model="minute" class="modal-input time-select">
            <option v-for="m in ['00','10','20','30','40','50']" :key="m" :value="m">{{ m }}</option>
          </select>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn-secondary" @click="emit('close')">취소</button>
        <button class="btn-primary" :disabled="saving" @click="save">저장</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { searchLaw } from '../api/law.js'
import { addLaw, updateLaw } from '../api/scheduler.js'

const props = defineProps({
  editingId:       { type: String, default: null },
  initialName:     { type: String, default: '' },
  initialInterval: { type: String, default: 'weekly' },
  initialDay:      { type: String, default: null },
  initialTime:     { type: String, default: '09:00' },
})
const emit = defineEmits(['close', 'saved'])

onMounted(() => {
  const sw = window.innerWidth - document.documentElement.clientWidth
  document.body.style.overflow = 'hidden'
  document.body.style.paddingRight = `${sw}px`
})
onUnmounted(() => {
  document.body.style.overflow = ''
  document.body.style.paddingRight = ''
})

const DAYS = ['월','화','수','목','금','토','일']

const name     = ref(props.initialName)
const interval = ref(props.initialInterval)
const day      = ref(props.initialDay || '월')
const hour     = ref(props.initialTime.split(':')[0] || '09')
const minute   = ref(props.initialTime.split(':')[1] || '00')
const saving   = ref(false)
const suggestions = ref([])

let acTimer = null
function onNameInput() {
  clearTimeout(acTimer)
  const q = name.value.trim()
  if (q.length < 1) { suggestions.value = []; return }
  acTimer = setTimeout(() => fetchSuggestions(q), 280)
}

async function fetchSuggestions(q) {
  try {
    const data = await searchLaw(q, 1, 10)
    suggestions.value = (data.laws || []).map(l => l['법령명한글'] || '').filter(Boolean)
  } catch { suggestions.value = [] }
}

function onIntervalChange() {
  if (interval.value === 'weekly') day.value = '월'
  else if (interval.value === 'monthly') day.value = '1'
  else day.value = null
}

function pad(n) { return String(n).padStart(2, '0') }

async function save() {
  if (!name.value.trim()) return
  saving.value = true
  try {
    const body = {
      name: name.value.trim(),
      interval: interval.value,
      day: interval.value !== 'daily' ? day.value : null,
      time: `${hour.value}:${minute.value}`,
    }
    if (props.editingId) await updateLaw(props.editingId, body)
    else await addLaw(body)
    emit('saved')
    emit('close')
  } catch (e) {
    alert(`저장 실패: ${e.message}`)
  } finally {
    saving.value = false
  }
}
</script>
