<template>
  <div id="tab-search" class="tab-panel" :class="{ active: active }">
    <div class="search-section">
      <form class="search-form" @submit.prevent="doSearch(query)">
        <input v-model="query" type="text" placeholder="법령명을 입력하세요  (예: 근로기준법)" autocomplete="off" spellcheck="false" />
        <button type="submit" :disabled="loading">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
          </svg>
        </button>
      </form>
      <div class="chips">
        <button v-for="q in CHIPS" :key="q" class="chip" @click="doSearch(q)">{{ q }}</button>
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
        <LawCard v-for="law in data.laws" :key="law['법령ID']" :law="law" @open-article="openArticle" />
        <Pagination :current="page" :total="totalPages" @go="doSearch(lastQuery, $event)" />
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, inject } from 'vue'
import { searchLaw } from '../api/law.js'
import LawCard from './LawCard.vue'
import Pagination from './Pagination.vue'

const props = defineProps({ active: Boolean })

const CHIPS = ['근로기준법', '자동차관리법', '민법', '형법', '소득세법']
const PAGE_SIZE = 10

const query     = ref('')
const lastQuery = ref('')
const page      = ref(1)
const state     = ref('')   // '' | 'loading' | 'done' | 'error'
const data      = ref({})
const errorMsg  = ref('')

const totalPages = computed(() => Math.ceil((data.value.total_cnt || 0) / PAGE_SIZE))

const openArticle = inject('openArticle')

async function doSearch(q, p = 1) {
  const trimmed = (q || '').trim()
  if (!trimmed) return
  query.value     = trimmed
  lastQuery.value = trimmed
  page.value      = p
  state.value     = 'loading'
  try {
    data.value  = await searchLaw(trimmed, p, PAGE_SIZE)
    state.value = 'done'
  } catch (e) {
    errorMsg.value = e.message
    state.value    = 'error'
  }
}
</script>
