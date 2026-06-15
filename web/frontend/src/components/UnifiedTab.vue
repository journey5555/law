<template>
  <div id="tab-unified" class="tab-panel" :class="{ active }">
    <div class="search-section">
      <form class="search-form" @submit.prevent="doSearch(query)">
        <input v-model="query" type="text" placeholder="법령명 또는 키워드를 입력하세요" autocomplete="off" spellcheck="false" />
        <button type="submit" :disabled="state === 'loading'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
          </svg>
        </button>
      </form>
    </div>

    <div class="unified-results">
      <div v-if="state === 'loading'" class="state-msg"><span class="spinner"></span>검색 중...</div>
      <div v-else-if="state === 'error'" class="state-msg error">{{ errorMsg }}</div>
      <div v-else-if="state === 'done'">
        <template v-if="lawData.laws?.length">
          <div class="unified-section-header">
            <span class="unified-section-title">법령</span>
            <span class="unified-section-count">{{ lawData.total_cnt?.toLocaleString() }}건</span>
          </div>
          <LawCard v-for="l in lawData.laws" :key="l['법령ID']" :law="l" />
        </template>

        <template v-if="precData.precs?.length">
          <div class="unified-section-header" :style="lawData.laws?.length ? 'margin-top:1.5rem' : ''">
            <span class="unified-section-title">판례</span>
            <span class="unified-section-count">{{ precData.total_cnt?.toLocaleString() }}건</span>
          </div>
          <PrecCard v-for="p in precData.precs" :key="p['판례일련번호']" :prec="p" />
        </template>

        <div v-if="!lawData.laws?.length && !precData.precs?.length" class="state-msg">
          "{{ lastQuery }}" 검색 결과가 없습니다.
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, inject } from 'vue'
import { searchLaw, searchPrec } from '../api/law.js'
import LawCard from './LawCard.vue'
import PrecCard from './PrecCard.vue'

const props = defineProps({ active: Boolean })

const query     = ref('')
const lastQuery = ref('')
const state     = ref('')
const errorMsg  = ref('')
const lawData   = ref({})
const precData  = ref({})

async function doSearch(q) {
  const trimmed = (q || '').trim()
  if (!trimmed) return
  lastQuery.value = trimmed
  state.value = 'loading'
  try {
    const [ld, pd] = await Promise.all([
      searchLaw(trimmed, 1, 5),
      searchPrec(trimmed, 1, 5),
    ])
    lawData.value = ld
    precData.value = pd
    state.value = 'done'
  } catch (e) {
    errorMsg.value = e.message
    state.value = 'error'
  }
}
</script>
