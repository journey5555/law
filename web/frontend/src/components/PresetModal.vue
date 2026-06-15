<template>
  <div class="modal-overlay" style="display:flex" @click.self="emit('close')">
    <div class="modal modal-wide">
      <div class="modal-header">
        <h3>인사 관련 추천 법령</h3>
        <button class="modal-close" @click="emit('close')">✕</button>
      </div>
      <div class="modal-body">
        <p class="modal-hint">수집할 법령을 선택하세요. 이미 추가된 법령은 비활성화됩니다.</p>
        <div class="preset-list">
          <div v-for="(items, cat) in grouped" :key="cat">
            <div class="preset-category-title">{{ cat }}</div>
            <div class="preset-items">
              <button
                v-for="item in items"
                :key="item.name"
                type="button"
                :class="['preset-chip', {
                  'preset-chip-added':    existing.has(item.name),
                  'preset-chip-selected': selected.has(item.name),
                }]"
                :disabled="existing.has(item.name)"
                @click="toggleSelect(item.name)"
              >{{ existing.has(item.name) ? '✓ ' : '' }}{{ item.name }}</button>
            </div>
          </div>
        </div>

        <div class="preset-schedule-row">
          <label class="modal-label">기본 수집 주기</label>
          <div class="preset-schedule-controls">
            <select v-model="interval" class="modal-input preset-interval-select" @change="onIntervalChange">
              <option value="daily">매일</option>
              <option value="weekly">매주</option>
              <option value="monthly">매월</option>
            </select>
            <div v-if="interval === 'weekly'" class="weekday-picker">
              <button
                v-for="d in DAYS"
                :key="d"
                type="button"
                :class="['weekday-btn', { active: day === d }]"
                @click="day = d"
              >{{ d }}</button>
            </div>
            <select v-else-if="interval === 'monthly'" v-model="day" class="modal-input">
              <option v-for="d in 28" :key="d" :value="String(d)">{{ d }}일</option>
            </select>
          </div>
        </div>

        <div class="preset-schedule-row">
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
      </div>
      <div class="modal-footer">
        <span class="preset-count-label">{{ selected.size ? `${selected.size}개 선택됨` : '' }}</span>
        <button class="btn-secondary" @click="emit('close')">취소</button>
        <button class="btn-primary" :disabled="adding || !selected.size" @click="addSelected">선택 추가</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { addLaw } from '../api/scheduler.js'

const props = defineProps({
  presets:  { type: Array, default: () => [] },
  existing: { type: Set,   default: () => new Set() },
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

const selected = ref(new Set())
const interval = ref('weekly')
const day      = ref('월')
const hour     = ref('09')
const minute   = ref('00')
const adding   = ref(false)

const grouped = computed(() => {
  const g = {}
  props.presets.forEach(p => {
    if (!g[p.category]) g[p.category] = []
    g[p.category].push(p)
  })
  return g
})

function onIntervalChange() {
  if (interval.value === 'weekly') day.value = '월'
  else if (interval.value === 'monthly') day.value = '1'
}

function toggleSelect(name) {
  const s = new Set(selected.value)
  if (s.has(name)) s.delete(name)
  else s.add(name)
  selected.value = s
}

function pad(n) { return String(n).padStart(2, '0') }

async function addSelected() {
  if (!selected.value.size) return
  adding.value = true
  const body = {
    interval: interval.value,
    day: interval.value !== 'daily' ? day.value : null,
    time: `${hour.value}:${minute.value}`,
  }
  let success = 0
  for (const name of selected.value) {
    try { await addLaw({ ...body, name }); success++ } catch {}
  }
  adding.value = false
  if (success) emit('saved')
  emit('close')
  if (success) alert(`${success}개 법령이 추가되었습니다.`)
}
</script>
