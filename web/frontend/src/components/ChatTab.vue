<template>
  <div id="tab-chat" class="tab-panel chat-panel" :class="{ active }">
    <div class="chat" ref="chatEl" aria-live="polite">
      <div v-if="messages.length === 0" class="welcome">
        <p>조문·판례·법령 해석 등 궁금한 것을 물어보세요.</p>
        <div class="chips">
          <button class="chip chat-chip" @click="send('근로기준법 1조가 뭐야')">근로기준법 1조</button>
          <button class="chip chat-chip" @click="send('연차 유급휴가 기준을 알려줘')">연차 기준</button>
          <button class="chip chat-chip" @click="send('해고 예고 기간은 어떻게 되나요?')">해고 예고</button>
        </div>
      </div>
      <div
        v-for="(msg, i) in messages"
        :key="i"
        :class="['message', msg.role, { error: msg.error }]"
      >
        <div class="message-label">{{ msg.role === 'user' ? '나' : '에이전트' }}</div>
        <div :class="['bubble', { loading: msg.loading }]">{{ msg.text }}</div>
      </div>
    </div>
    <div class="composer">
      <form class="search-form" @submit.prevent="send(input)">
        <textarea
          v-model="input"
          rows="1"
          placeholder="질문을 입력하세요..."
          autocomplete="off"
          :disabled="busy"
          @keydown.enter.exact.prevent="send(input)"
          @input="autoResize"
          ref="textareaEl"
        />
        <button type="submit" :disabled="busy">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 19V5M5 12l7-7 7 7"/>
          </svg>
        </button>
      </form>
      <p class="hint">Enter 전송 · Shift+Enter 줄바꿈</p>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick } from 'vue'
import { streamChat } from '../api/chat.js'

const props = defineProps({ active: Boolean })

const input     = ref('')
const busy      = ref(false)
const messages  = ref([])
const chatEl    = ref(null)
const textareaEl = ref(null)

function autoResize(e) {
  const el = e.target
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 120)}px`
}

function scrollBottom() {
  nextTick(() => { if (chatEl.value) chatEl.value.scrollTop = chatEl.value.scrollHeight })
}

async function send(text) {
  const message = (text || '').trim()
  if (!message || busy.value) return

  messages.value.push({ role: 'user', text: message })
  input.value = ''
  if (textareaEl.value) { textareaEl.value.style.height = 'auto' }
  scrollBottom()

  busy.value = true
  const botMsg = { role: 'assistant', text: '응답 생성 중...', loading: true, error: false }
  messages.value.push(botMsg)
  scrollBottom()

  try {
    botMsg.text    = ''
    botMsg.loading = false
    for await (const token of streamChat(message)) {
      botMsg.text += token
      scrollBottom()
    }
  } catch (e) {
    botMsg.text  = e.message || '요청 중 오류가 발생했습니다.'
    botMsg.error = true
    botMsg.loading = false
  } finally {
    busy.value = false
  }
}
</script>
