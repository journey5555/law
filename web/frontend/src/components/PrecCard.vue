<template>
  <div class="law-card" :class="{ expanded }" @click="toggle">
    <div class="card-main">
      <div class="card-left">
        <div class="card-title">{{ name }}</div>
        <div class="card-meta">
          <span v-if="caseNo">{{ caseNo }}</span>
          <span v-if="court">{{ court }}</span>
          <span v-if="date">{{ date }}</span>
          <span v-if="caseType" class="badge">{{ caseType }}</span>
          <span v-if="judgeType" class="badge badge-gray">{{ judgeType }}</span>
        </div>
      </div>
      <div class="card-arrow">›</div>
    </div>

    <div v-if="expanded" class="card-detail">
      <div v-if="detailState === 'loading'" class="state-msg">
        <span class="spinner"></span>판례 불러오는 중...
      </div>
      <div v-else-if="detailState === 'error'" class="state-msg error">{{ detailError }}</div>
      <template v-else>
        <div class="card-detail-toolbar">
          <button class="btn-summarize" :disabled="summarizing" @click.stop="doSummarize">
            <span v-if="summarizing" class="spinner" style="width:11px;height:11px;margin-right:5px"></span>
            {{ summarizing ? '요약 중...' : summaryText ? '다시 요약' : 'AI 요약' }}
          </button>
        </div>
        <div v-if="summaryText" class="summary-box">
          <div class="summary-box-header">✦ AI 요약</div>
          {{ summaryText }}
        </div>
        <div v-if="summarizeError" class="state-msg error" style="font-size:0.82rem">{{ summarizeError }}</div>
        <div v-html="detailHtml" @click.stop="handleDetailClick" />
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, inject } from 'vue'
import { getPrec, summarize } from '../api/law.js'
import { esc, stripHtml } from '../utils/format.js'
import { extractCitations } from '../utils/articles.js'
import { fmtDate } from '../utils/format.js'

const props = defineProps({ prec: Object })
const openArticle = inject('openArticle')

const expanded       = ref(false)
const loaded         = ref(false)
const detailState    = ref('')
const detailError    = ref('')
const detailHtml     = ref('')
const summarizing    = ref(false)
const summaryText    = ref('')
const summarizeError = ref('')
let   _precData      = null

const name      = computed(() => props.prec['사건명'] || '(사건명 없음)')
const id        = computed(() => props.prec['판례정보일련번호'] || props.prec['판례일련번호'] || '')
const caseNo    = computed(() => props.prec['사건번호'] || '')
const court     = computed(() => props.prec['법원명'] || '')
const date      = computed(() => fmtDate(props.prec['선고일자'] || ''))
const caseType  = computed(() => props.prec['사건종류명'] || '')
const judgeType = computed(() => props.prec['판결유형'] || '')

async function toggle() {
  expanded.value = !expanded.value
  if (!expanded.value || loaded.value) return

  detailState.value = 'loading'
  try {
    const data = await getPrec(id.value)
    _precData = data
    detailHtml.value = buildPrecHtml(data)
    detailState.value = 'done'
    loaded.value = true
  } catch (e) {
    detailError.value = e.message
    detailState.value = 'error'
  }
}

async function doSummarize() {
  if (!_precData) return
  const text = [_precData.issues, _precData.summary].filter(Boolean).join('\n').trim()
  if (!text) return
  summarizing.value = true
  summarizeError.value = ''
  try {
    const res = await summarize(text)
    summaryText.value = res.summary
  } catch (e) {
    summarizeError.value = e.message
  } finally {
    summarizing.value = false
  }
}

function buildPrecHtml(data) {
  const sections = [
    { label: '판시사항', value: data.issues   },
    { label: '판결요지', value: data.summary  },
    { label: '참조판례', value: data.ref_cases },
  ]
  let html = sections
    .filter(s => s.value?.trim())
    .map(s => `<div class="article">
      <div class="article-header">${esc(s.label)}</div>
      <div class="article-content">${esc(stripHtml(s.value))}</div>
    </div>`)
    .join('')

  if (data.ref_articles?.trim()) {
    const citations = extractCitations(data.ref_articles)
    const citHtml = citations.length
      ? `<div class="law-links">${citations.map(c =>
          `<button class="law-link-btn" data-law="${esc(c.lawName)}" data-jo="${c.joNum}" data-jo-sub="${c.joSub}">
            ${esc(c.lawName)} ${esc(c.joText)}
          </button>`).join('')}</div>`
      : ''
    html += `<div class="article">
      <div class="article-header">참조조문</div>
      <div class="article-content">${esc(stripHtml(data.ref_articles))}</div>
      ${citHtml}
    </div>`
  }

  return html || '<div class="state-msg">상세 내용이 없습니다.</div>'
}

function handleDetailClick(e) {
  const btn = e.target.closest('.law-link-btn')
  if (!btn) return
  openArticle(btn.dataset.law, Number(btn.dataset.jo), Number(btn.dataset.joSub || 0))
}
</script>
