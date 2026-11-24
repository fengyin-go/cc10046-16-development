import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type { ActionResult, EntryRow, OverviewResult, PageResult } from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

// ---------------------------------------------------------------------------
// 采集会话归属：领取 / 审批 / 历史
// ---------------------------------------------------------------------------

export type ScopeValue = string

export interface AttributionSnapshot {
  processing?: number
  处理次序?: number
  plan_id?: string
  计划标识?: string
  requested_plan_id?: string
  申请计划标识?: string
  adopted_plan_id?: string
  实际采用计划?: string
  site?: string
  来源站点?: string
  purpose?: string
  用途?: string
  license_id?: string
  许可标识?: string
  license_version?: string
  许可版本?: string
  permission?: string
  权限类型?: string
  scope?: ScopeValue[]
  granted_scopes?: ScopeValue[]
  资料范围?: ScopeValue[]
  获准资料范围?: ScopeValue[]
  session_id?: string
  会话标识?: string
  claim_key?: string
  领取标识?: string
  decision?: string
  processed_at?: string
  处理时间?: string
  [key: string]: unknown
}

export interface ClaimResult {
  ok: boolean
  obtained?: boolean
  claimed?: boolean
  session?: EntryRow | null
  会话?: EntryRow | null
  session_id?: string
  会话标识?: string
  approval_id?: string
  核准记录标识?: string
  duplicate?: boolean
  replayed?: boolean
  fallback_used?: boolean
  pending_review?: boolean
  plan_id?: string
  计划标识?: string
  requested_plan_id?: string
  申请计划标识?: string
  adopted_plan_id?: string
  实际采用计划?: string
  license_version?: string
  许可版本?: string
  granted_scopes?: ScopeValue[]
  获准资料范围?: ScopeValue[]
  message?: string
  归属?: AttributionSnapshot
  attribution?: AttributionSnapshot
  history?: AttributionSnapshot[]
  [key: string]: unknown
}

async function postJson<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
  if (!response.ok) throw new Error(`接口返回 ${response.status}`)
  return (await response.json()) as T
}

export function claimAttribution(body: Record<string, unknown>): Promise<ClaimResult> {
  return postJson<ClaimResult>('/api/source_auth/claim', body)
}

export function approveExpansion(body: Record<string, unknown>): Promise<{
  ok: boolean
  approved?: boolean
  message?: string
  license?: EntryRow
  plan?: EntryRow
}> {
  return postJson('/api/source_auth/approve', body)
}

export async function fetchSessionHistory(sessionId: string | number): Promise<{
  ok: boolean
  found?: boolean
  history: AttributionSnapshot[]
  处理历史?: AttributionSnapshot[]
  attribution?: AttributionSnapshot
  归属?: AttributionSnapshot
  session?: EntryRow
}> {
  const response = await request(`/api/session_manager/${encodeURIComponent(String(sessionId))}/history`)
  if (!response.ok) throw new Error('会话历史读取失败')
  return await response.json()
}

export interface ScenarioBundle {
  site: string
  plans: EntryRow[]
  licenses: EntryRow[]
  claims: EntryRow[]
}

export async function fetchScenario(): Promise<ScenarioBundle> {
  const response = await request('/api/attribution/scenario')
  if (!response.ok) throw new Error('归属场景读取失败')
  return await response.json()
}
