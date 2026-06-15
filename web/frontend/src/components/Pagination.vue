<template>
  <div v-if="total > 1" class="pagination">
    <button class="page-btn" :disabled="current === 1" @click="emit('go', current - 1)">‹ 이전</button>
    <template v-if="start > 1">
      <button class="page-btn" @click="emit('go', 1)">1</button>
      <span v-if="start > 2" class="page-ellipsis">…</span>
    </template>
    <button
      v-for="p in range"
      :key="p"
      :class="['page-btn', { active: p === current }]"
      @click="emit('go', p)"
    >{{ p }}</button>
    <template v-if="end < total">
      <span v-if="end < total - 1" class="page-ellipsis">…</span>
      <button class="page-btn" @click="emit('go', total)">{{ total }}</button>
    </template>
    <button class="page-btn" :disabled="current === total" @click="emit('go', current + 1)">다음 ›</button>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ current: Number, total: Number })
const emit  = defineEmits(['go'])

const WINDOW = 2
const start  = computed(() => Math.max(1, props.current - WINDOW))
const end    = computed(() => Math.min(props.total, props.current + WINDOW))
const range  = computed(() => Array.from({ length: end.value - start.value + 1 }, (_, i) => start.value + i))
</script>
