<template>
  <section class="page" :data-module="meta.key">
    <header class="page-head">
      <div>
        <h2>{{ meta.name }}</h2>
        <p class="page-desc">{{ meta.desc }}</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">
          登记{{ meta.entity }}
        </button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">
          导出{{ meta.name }}清单
        </button>
      </div>
    </header>

    <AttributionPanel v-if="meta.key === 'source_auth'" @changed="reload" />

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p class="status-legend">
      <span v-for="item in statusSummary" :key="item.status" class="legend-item">
        {{ item.status }}：{{ item.count }}
      </span>
    </p>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in meta.fields" :key="column">{{ column }}</th>
          <th>当前状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in meta.fields" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.status }}</td>
          <td class="row-actions">
            <button
              v-for="action in meta.actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button
              v-if="meta.key === 'session_manager'"
              class="link"
              type="button"
              :data-testid="`attribution-detail-${row.id}`"
              @click="openAttributionDetail(row)"
            >
              归属/历史
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="meta.fields.length + 2" class="empty-state">
            暂无{{ meta.name }}数据，可先登记{{ meta.entity }}
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记{{ meta.entity }}</h3>
        <label v-for="field in meta.fields" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <div v-if="showHistory" class="modal-backdrop" data-testid="history-modal">
      <div class="modal history-modal" role="dialog" aria-modal="true">
        <h3>会话归属与处理历史</h3>
        <p v-if="historyError" class="error-text">{{ historyError }}</p>
        <template v-if="historyData">
          <dl class="history-summary">
            <div><dt>会话标识</dt><dd>{{ historySessionLabel }}</dd></div>
            <div><dt>实际计划</dt><dd>{{ historyData.attribution?.实际采用计划 ?? historyData.attribution?.plan_id ?? '—' }}</dd></div>
            <div><dt>许可版本</dt><dd>{{ historyData.attribution?.许可版本 ?? historyData.attribution?.license_version ?? '—' }}</dd></div>
            <div><dt>来源站点</dt><dd>{{ historyData.attribution?.来源站点 ?? historyData.attribution?.site ?? '—' }}</dd></div>
          </dl>
          <p v-if="!(historyData.history ?? []).length" class="empty-state">该会话暂无归属处理历史</p>
          <ol class="history-modal-list">
            <li v-for="(item, idx) in historyData.history ?? []" :key="`${item.claim_key ?? idx}`"
                :data-testid="`modal-history-row-${idx}`"
                :data-version="String(item.许可版本 ?? item.license_version ?? '')">
              <strong>第 {{ item.处理次序 ?? item.processing ?? idx + 1 }} 次处理</strong>
              <span>计划：{{ item.计划标识 ?? item.plan_id }}</span>
              <span>许可版本：{{ item.许可版本 ?? item.license_version }}</span>
              <span>范围：{{ formatScope(item.资料范围 ?? item.granted_scopes) }}</span>
              <span class="history-time">{{ item.处理时间 ?? item.processed_at }}</span>
            </li>
          </ol>
        </template>
        <div class="page-actions">
          <button class="btn primary" data-testid="close-history" type="button" @click="showHistory = false">关闭</button>
        </div>
      </div>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条{{ meta.name }}记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  createEntry,
  downloadEntries,
  fetchSessionHistory,
  listEntries,
  moduleMeta,
  runAction as applyAction,
  type AttributionSnapshot,
} from '@/api/backend-service'
import type { EntryRow } from '@/data/types'
import AttributionPanel from './AttributionPanel.vue'

interface SessionHistoryDetail {
  history?: AttributionSnapshot[]
  attribution?: AttributionSnapshot
  处理历史?: AttributionSnapshot[]
  归属?: AttributionSnapshot
}

const props = defineProps<{ moduleKey: string }>()
const meta = moduleMeta(props.moduleKey)
const rows = ref<EntryRow[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = meta.fields.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})
const stats = computed(() => [
  { label: meta.metrics[0], value: total.value },
  { label: meta.metrics[1], value: rows.value.filter((row) => row.status === meta.statuses[1]).length },
  {
    label: meta.metrics[2],
    value: rows.value.filter((row) => row.status === meta.statuses[meta.statuses.length - 1]).length,
  },
])
const statusSummary = computed(() =>
  meta.statuses.map((status) => ({
    status,
    count: rows.value.filter((row) => String(row.status) === status).length,
  })),
)

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  try {
    await downloadEntries(meta.key, filters.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(meta.fields.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const result = await createEntry(meta.key, createValues.value)
    if (!result.ok) throw new Error(result.message)
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: EntryRow) {
  errorMessage.value = ''
  try {
    const result = await applyAction(meta.key, Number(row.id), action)
    if (!result.ok) throw new Error(result.message)
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await listEntries(meta.key, filters.value)
    rows.value = payload.items
    total.value = payload.total
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '业务列表读取失败'
  }
}

const showHistory = ref(false)
const historyError = ref('')
const historyData = ref<SessionHistoryDetail | null>(null)
const historySessionLabel = ref('')

function formatScope(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join('、') : '—'
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
}

async function openAttributionDetail(row: EntryRow) {
  historyError.value = ''
  historyData.value = null
  historySessionLabel.value = String(row['会话标识'] ?? row.id)
  showHistory.value = true
  try {
    historyData.value = await fetchSessionHistory(String(row['会话标识'] ?? row.id))
  } catch (error) {
    historyError.value = error instanceof Error ? error.message : '归属历史读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.history-modal { max-width: 720px; width: min(720px, 92vw); }
.history-summary {
  display: grid; grid-template-columns: 1fr 1fr; gap: 8px 18px; margin: 10px 0;
}
.history-summary dt { font-size: 12px; color: #6b7280; }
.history-summary dd { margin: 2px 0 0; font-weight: 600; }
.history-modal-list {
  list-style: none; margin: 8px 0 16px; padding: 0;
  display: flex; flex-direction: column; gap: 8px; max-height: 50vh; overflow: auto;
}
.history-modal-list li {
  display: flex; flex-direction: column; gap: 3px;
  border: 1px solid #e5e9f0; border-left: 4px solid #6366f1;
  border-radius: 8px; padding: 8px 12px; font-size: 13.5px;
}
.history-time { color: #9ca3af; font-size: 12px; }
</style>
