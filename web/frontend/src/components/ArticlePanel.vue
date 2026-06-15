<template>
  <div :class="['article-panel', { open }]">
    <div class="panel-inner">
      <div class="panel-header">
        <div class="panel-title-wrap">
          <span class="panel-law-name">{{ lawName }}</span>
          <span class="panel-jo-title">{{ joTitle }}</span>
        </div>
        <button class="panel-close" @click="close">✕</button>
      </div>
      <div class="panel-content" v-html="contentHtml" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { getArticle } from '../api/law.js'
import { filterArticles, buildArticleHtml } from '../utils/articles.js'

const open    = ref(false)
const lawName = ref('')
const joTitle = ref('')
const contentHtml = ref('<div class="state-msg"><span class="spinner"></span>불러오는 중...</div>')

async function openPanel(name, joNum, joSub = 0) {
  lawName.value   = name
  joTitle.value   = `제${joNum}조${joSub ? `의${joSub}` : ''}`
  contentHtml.value = '<div class="state-msg"><span class="spinner"></span>불러오는 중...</div>'
  open.value = true

  try {
    const data     = await getArticle(name, joNum, joSub)
    const articles = filterArticles(data.articles || [])
    lawName.value  = data.searched_law_name || name
    contentHtml.value = articles.length
      ? articles.map(buildArticleHtml).join('')
      : '<div class="state-msg">조문 내용이 없습니다.</div>'
  } catch (e) {
    contentHtml.value = `<div class="state-msg error">${e.message}</div>`
  }
}

function close() { open.value = false }

defineExpose({ openPanel })
</script>
