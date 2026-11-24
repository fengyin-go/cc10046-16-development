<template>
  <section class="attr-panel" data-testid="attribution-panel">
    <header class="attr-head">
      <h3>采集会话归属 · 按计划核对来源与许可版本</h3>
      <p class="attr-tip">
        关联站点、用途与许可版本；独立只读权限只能使用获准资料范围。同站另一份许可不能给本计划授权。
      </p>
    </header>

    <div class="attr-grid">
      <div class="attr-block">
        <h4>同站采集计划</h4>
        <ul class="attr-list" data-testid="plan-list">
          <li v-for="plan in plans" :key="String(plan.plan_code)" class="attr-item">
            <label class="pick">
              <input type="radio" name="plan" :value="String(plan.plan_code)" v-model="planCode"
                     :data-testid="`pick-plan-${plan.plan_code}`" />
              <span>
                <strong>{{ plan.计划标识 }}</strong>
                {{ plan.计划名称 }}
              </span>
            </label>
            <span class="badge" :data-status="String(plan.status)">{{ plan.status }}</span>
            <div class="attr-meta">站点：{{ plan.来源站点 }}　用途：{{ plan.用途 }}</div>
          </li>
        </ul>
      </div>

      <div class="attr-block">
        <h4>来源许可版本</h4>
        <ul class="attr-list" data-testid="license-list">
          <li v-for="lic in licenses" :key="String(lic.license_code)" class="attr-item">
            <strong>{{ lic.许可标识 }}</strong>
            <span class="badge" :data-status="String(lic.status)">{{ lic.许可版本 }} · {{ lic.status }}</span>
            <div class="attr-meta">
              归属计划：{{ lic.计划标识 }}　权限：{{ lic.权限类型 }}
            </div>
            <div class="attr-meta">获准范围：{{ scopeText(lic.获准资料范围) }}</div>
          </li>
        </ul>
      </div>
    </div>

    <div class="attr-actions">
      <label class="key-field">
        <span>领取键（中断重试沿用同一键）</span>
        <input v-model="claimKey" data-testid="claim-key" placeholder="例如 RESP-0001" />
      </label>
      <button class="btn primary" data-testid="claim-once" :disabled="busy" type="button" @click="claim(false)">
        通过认证入口领取
      </button>
      <button class="btn" data-testid="claim-replay" :disabled="busy || !lastSessionId" type="button" @click="claim(true)">
        模拟响应中断 · 同键重复领取
      </button>
      <button class="btn" data-testid="new-key-claim" :disabled="busy" type="button" @click="claim(false, true)">
        换一个新领取键再次提交
      </button>
      <button class="btn ghost" data-testid="approve-expansion" :disabled="busy" type="button" @click="approve">
        批准所选计划扩大的范围
      </button>
      <button class="btn ghost" data-testid="reload-scenario" type="button" @click="loadScenario">刷新</button>
    </div>

    <p v-if="error" class="error-text" data-testid="attr-error">{{ error }}</p>
    <p v-if="notice" class="attr-notice" data-testid="attr-notice">{{ notice }}</p>

    <div v-if="result" class="attr-result" data-testid="claim-result">
      <h4>本次领取结果</h4>
      <div class="result-tags">
        <span class="tag" :class="result.obtained ? 'ok' : 'wait'" data-testid="claim-obtained">
          {{ result.obtained ? '已取得实际会话' : '本次没有会话 · 等待新范围审核' }}
        </span>
        <span v-if="result.duplicate" class="tag replay" data-testid="claim-duplicate">
          重复领取 · 已接回原核准记录，未另建会话
        </span>
        <span v-if="result.fallback_used" class="tag old" data-testid="claim-fallback">
          降级使用旧许可只读会话
        </span>
        <span v-if="result.pending_review" class="tag wait" data-testid="claim-pending">扩大范围待审</span>
      </div>
      <dl class="result-grid">
        <div><dt>申请计划</dt><dd>{{ result.申请计划标识 ?? result.requested_plan_id ?? '—' }}</dd></div>
        <div><dt>实际采用计划</dt><dd data-testid="result-adopted-plan">{{ result.实际采用计划 ?? result.adopted_plan_id ?? result.计划标识 ?? '—' }}</dd></div>
        <div><dt>许可版本</dt><dd data-testid="result-license-version">{{ result.许可版本 ?? result.license_version ?? '—' }}</dd></div>
        <div><dt>会话标识</dt><dd data-testid="result-session-id">{{ result.会话标识 ?? result.session_id ?? '—' }}</dd></div>
        <div><dt>核准记录</dt><dd>{{ result.核准记录标识 ?? result.approval_id ?? '—' }}</dd></div>
        <div><dt>获准资料范围</dt><dd>{{ scopeText(result.获准资料范围 ?? result.granted_scopes) }}</dd></div>
      </dl>
      <p class="attr-meta">{{ result.message }}</p>
      <div class="attr-actions">
        <button v-if="lastSessionId" class="link" data-testid="open-history" type="button" @click="openHistory(lastSessionId)">
          从会话详情重新打开历史数据
        </button>
      </div>
    </div>

    <div v-if="history.length" class="attr-history" data-testid="history-panel">
      <h4>会话处理历史（{{ history.length }} 次处理）<span v-if="historySessionId" class="attr-meta">　{{ historySessionId }}</span></h4>
      <ol class="history-list">
        <li v-for="(item, idx) in history" :key="`${item.claim_key ?? idx}`" class="history-item"
            :data-testid="`history-row-${idx}`" :data-version="String(item.许可版本 ?? item.license_version ?? '')">
          <div class="history-head">
            <strong>第 {{ item.处理次序 ?? item.processing ?? idx + 1 }} 次处理</strong>
            <span class="badge">{{ item.计划标识 ?? item.plan_id }} · {{ item.许可版本 ?? item.license_version }}</span>
            <span class="attr-meta">{{ item.处理时间 ?? item.processed_at }}</span>
          </div>
          <div class="attr-meta">
            来源：{{ item.来源站点 ?? item.site }}　用途：{{ item.用途 ?? item.purpose }}
            　会话：{{ item.会话标识 ?? item.session_id ?? '未生成' }}
          </div>
          <div class="attr-meta">资料范围：{{ scopeText(item.资料范围 ?? item.granted_scopes) }}</div>
        </li>
      </ol>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import {
  approveExpansion,
  claimAttribution,
  fetchScenario,
  fetchSessionHistory,
  type AttributionSnapshot,
  type ClaimResult,
} from '@/api/backend-service'
import type { EntryRow } from '@/data/types'

const emit = defineEmits<{ (event: 'changed'): void }>()

const plans = ref<EntryRow[]>([])
const licenses = ref<EntryRow[]>([])
const planCode = ref('PLAN-EXPAND-02')
const claimKey = ref(`UI-${Math.random().toString(36).slice(2, 10)}`)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const result = ref<ClaimResult | null>(null)
const lastSessionId = ref('')
const history = ref<AttributionSnapshot[]>([])
const historySessionId = ref('')

function scopeText(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join('、') : '—'
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
}

async function loadScenario() {
  error.value = ''
  try {
    const data = await fetchScenario()
    plans.value = data.plans
    licenses.value = data.licenses
  } catch (e) {
    error.value = e instanceof Error ? e.message : '场景读取失败'
  }
}

async function claim(replaySameKey: boolean, forceNewKey = false) {
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    if (forceNewKey || (!replaySameKey && !claimKey.value)) {
      claimKey.value = `UI-${Date.now()}`
    }
    const body: Record<string, unknown> = {
      plan_id: planCode.value,
      claim_key: claimKey.value,
    }
    const res = await claimAttribution(body)
    result.value = res
    const sid = String(res.会话标识 ?? res.session_id ?? '')
    if (sid) lastSessionId.value = sid
    if (res.duplicate) notice.value = '已接回原核准记录，返回的是同一个会话，没有另建。'
    emit('changed')
    await loadScenario()
    if (sid) await openHistory(sid)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '领取失败'
  } finally {
    busy.value = false
  }
}

async function approve() {
  busy.value = true
  error.value = ''
  try {
    const res = await approveExpansion({ plan_id: planCode.value, approver: '值班员（界面审批）' })
    notice.value = res.message ?? '扩大范围已批准'
    await loadScenario()
    emit('changed')
  } catch (e) {
    error.value = e instanceof Error ? e.message : '批准失败'
  } finally {
    busy.value = false
  }
}

async function openHistory(sessionId: string | number) {
  error.value = ''
  try {
    const detail = await fetchSessionHistory(sessionId)
    history.value = detail.history ?? detail.处理历史 ?? []
    historySessionId.value = String(sessionId)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '历史读取失败'
  }
}

defineExpose({ openHistory })

onMounted(loadScenario)
</script>

<style scoped>
.attr-panel {
  border: 1px solid #d8dee9;
  border-radius: 12px;
  padding: 16px 18px;
  margin-bottom: 18px;
  background: #f8fafc;
}
.attr-head h3 { margin: 0 0 4px; }
.attr-tip { margin: 0 0 12px; color: #5b6472; font-size: 13px; }
.attr-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.attr-block { background: #fff; border: 1px solid #e5e9f0; border-radius: 10px; padding: 10px 12px; }
.attr-block h4 { margin: 0 0 8px; font-size: 14px; }
.attr-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.attr-item { border-bottom: 1px dashed #e5e9f0; padding-bottom: 8px; }
.attr-item:last-child { border-bottom: none; padding-bottom: 0; }
.pick { display: flex; gap: 8px; align-items: baseline; cursor: pointer; }
.attr-meta { color: #6b7280; font-size: 12.5px; margin-top: 3px; word-break: break-all; }
.badge {
  display: inline-block; font-size: 12px; padding: 1px 8px; border-radius: 999px;
  background: #eef2ff; color: #3730a3; margin-left: 6px;
}
.badge[data-status='待审核'], .badge[data-status='待审批'] { background: #fef3c7; color: #92400e; }
.badge[data-status='有效'], .badge[data-status='生效中'], .badge[data-status='已核准'] { background: #dcfce7; color: #166534; }
.attr-actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: end; margin: 14px 0 6px; }
.key-field { display: flex; flex-direction: column; gap: 4px; font-size: 12.5px; color: #374151; }
.key-field input { padding: 7px 10px; border: 1px solid #cbd5e1; border-radius: 8px; min-width: 240px; }
.attr-notice { color: #166534; font-size: 13px; }
.attr-result { background: #fff; border: 1px solid #c7d2fe; border-radius: 10px; padding: 12px 14px; margin-top: 10px; }
.result-tags { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
.tag { font-size: 12.5px; padding: 3px 10px; border-radius: 999px; }
.tag.ok { background: #dcfce7; color: #166534; }
.tag.wait { background: #fef3c7; color: #92400e; }
.tag.replay { background: #e0e7ff; color: #3730a3; }
.tag.old { background: #f1f5f9; color: #475569; border: 1px dashed #94a3b8; }
.result-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px 16px; margin: 0; }
.result-grid dt { font-size: 12px; color: #6b7280; }
.result-grid dd { margin: 2px 0 0; font-size: 13.5px; font-weight: 600; word-break: break-all; }
.attr-history { margin-top: 14px; }
.history-list { list-style: none; margin: 8px 0 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
.history-item { background: #fff; border: 1px solid #e5e9f0; border-left: 4px solid #6366f1; border-radius: 8px; padding: 8px 12px; }
.history-head { display: flex; align-items: center; gap: 8px; }
@media (max-width: 960px) { .attr-grid, .result-grid { grid-template-columns: 1fr; } }
</style>
