<template>
  <div class="law-card" :class="{ expanded }" @click="toggle">
    <div class="card-main">
      <div class="card-left">
        <div class="card-title">{{ name }}</div>
        <div class="card-meta">
          <span v-if="dept">{{ dept }}</span>
          <span v-if="date">시행 {{ date }}</span>
          <span v-if="kind" class="badge">{{ kind }}</span>
        </div>
      </div>
      <div class="card-arrow">›</div>
    </div>

    <div v-if="expanded" class="card-detail">
      <div v-if="detailState === 'loading'" class="state-msg">
        <span class="spinner"></span>조문 불러오는 중...
      </div>
      <div v-else-if="detailState === 'error'" class="state-msg error">{{ detailError }}</div>
      <template v-else>
        <div v-html="detailHtml" @click.stop="handleDetailClick" />
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, inject } from 'vue'
import { getLaw } from '../api/law.js'
import { filterArticles, buildArticleHtml } from '../utils/articles.js'
import { fmtDate } from '../utils/format.js'

const props = defineProps({ law: Object })
const emit  = defineEmits(['open-article'])

const openArticle = inject('openArticle')

const expanded    = ref(false)
const loaded      = ref(false)
const detailState = ref('')
const detailError = ref('')
const detailHtml  = ref('')

const name = computed(() => props.law['법령명한글'] || props.law['법령명'] || '(이름 없음)')
const id   = computed(() => props.law['법령ID'] || '')
const dept = computed(() => props.law['소관부처명'] || '')
const date = computed(() => fmtDate(props.law['시행일자'] || props.law['공포일자'] || ''))
const kind = computed(() => props.law['법령구분명'] || props.law['법종구분명'] || '')

async function toggle() {
  expanded.value = !expanded.value
  if (!expanded.value || loaded.value) return

  detailState.value = 'loading'
  try {
    const data    = await getLaw(id.value)
    const articles = filterArticles(data.articles || [])
    detailHtml.value = articles.length
      ? articles.map(buildArticleHtml).join('')
      : '<div class="state-msg">조문 정보가 없습니다.</div>'
    detailState.value = 'done'
    loaded.value = true
  } catch (e) {
    detailError.value = e.message
    detailState.value = 'error'
  }
}

function handleDetailClick(e) {
  const btn = e.target.closest('.law-link-btn')
  if (!btn) return
  openArticle(btn.dataset.law, Number(btn.dataset.jo), Number(btn.dataset.joSub || 0))
}
</script>
