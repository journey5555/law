<template>
  <div id="tab-prec" class="tab-panel" :class="{ active }">
    <div class="search-section">
      <form class="search-form" @submit.prevent="doSearch(query)">
        <input v-model="query" type="text" placeholder="키워드를 입력하세요  (예: 부당해고, 손해배상)" autocomplete="off" spellcheck="false" />
        <button type="submit" :disabled="loading">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
          </svg>
        </button>
      </form>
      <div class="chips">
        <button v-for="q in CHIPS" :key="q" class="chip prec-chip" @click="doSearch(q)">{{ q }}</button>
      </div>
    </div>

    <div class="results">
      <template v-if="state === 'loading'">
        <div class="state-msg"><span class="spinner"></span>검색 중...</div>
      </template>
      <template v-else-if="state === 'error'">
        <div class="state-msg error">{{ errorMsg }}</div>
      </template>
      <template v-else-if="state === 'done'">
        <div class="results-header">
          총 <strong>{{ data.total_cnt?.toLocaleString() }}</strong>건 &nbsp;·&nbsp; "{{ data.keyword }}"
        </div>

        <!-- 법원 필터 -->
        <div v-if="courtGroups.length > 1" class="court-filter">
          <button
            v-for="g in ['전체', ...courtGroups]"
            :key="g"
            :class="['court-btn', { active: activeFilter === g }]"
            @click="activeFilter = g"
          >
            {{ g }} <span class="court-count">{{ g === '전체' ? data.precs.length : courtCount[g] }}</span>
          </button>
        </div>

        <PrecCard
          v-for="prec in filteredPrecs"
          :key="prec['판례일련번호']"
          :prec="prec"
        />
        <Pagination :current="page" :total="totalPages" @go="doSearch(lastQuery, $event)" />
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { searchPrec } from '../api/law.js'
import PrecCard from './PrecCard.vue'
import Pagination from './Pagination.vue'

const props = defineProps({ active: Boolean })

const CHIPS = ['부당해고', '손해배상', '계약해지', '명예훼손', '임금체불']
const PAGE_SIZE = 10
const COURT_ORDER = ['대법원', '고등법원', '지방법원', '행정법원', '가정법원', '특허법원', '헌법재판소']

const query       = ref('')
const lastQuery   = ref('')
const page        = ref(1)
const state       = ref('')
const data        = ref({})
const errorMsg    = ref('')
const activeFilter = ref('전체')

const totalPages = computed(() => Math.ceil((data.value.total_cnt || 0) / PAGE_SIZE))

function courtGroup(court) {
  return COURT_ORDER.find(c => (court || '').includes(c)) || '기타'
}

const courtCount = computed(() => {
  const counts = {}
  ;(data.value.precs || []).forEach(p => {
    const g = courtGroup(p['법원명'])
    counts[g] = (counts[g] || 0) + 1
  })
  return counts
})

const courtGroups = computed(() => {
  const all = COURT_ORDER.filter(c => courtCount.value[c])
  if (courtCount.value['기타']) all.push('기타')
  return all
})

const filteredPrecs = computed(() => {
  if (activeFilter.value === '전체') return data.value.precs || []
  return (data.value.precs || []).filter(p => courtGroup(p['법원명']) === activeFilter.value)
})

async function doSearch(q, p = 1) {
  const trimmed = (q || '').trim()
  if (!trimmed) return
  query.value      = trimmed
  lastQuery.value  = trimmed
  page.value       = p
  activeFilter.value = '전체'
  state.value      = 'loading'
  try {
    data.value  = await searchPrec(trimmed, p, PAGE_SIZE)
    state.value = 'done'
  } catch (e) {
    errorMsg.value = e.message
    state.value    = 'error'
  }
}
</script>
