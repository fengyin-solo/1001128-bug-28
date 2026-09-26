<template>
  <section class="page" data-module="customer">
    <header class="page-head">
      <div>
        <h2>货主档案管理</h2>
        <p class="page-desc">维护货主，围绕客户编码、客户名称、客户类型、联系人做登记、筛选与状态流转。仅客户编码对应的责任人可提交变更，其他账号只读。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记货主</button>
        <button class="btn" type="button" @click="exportRows">导出货主档案清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>客户编码</span>
        <input v-model="keyword" placeholder="按客户编码检索" />
      </label>
      <label class="filter-item">
        <span>客户状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <p v-if="readonlyHint" class="readonly-hint">{{ readonlyHint }}</p>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <template v-if="canChange(row)">
              <button
                v-for="action in availableActions(row)"
                :key="action"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </template>
            <span v-else class="readonly-tag">仅查看</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无货主档案数据，可先登记货主</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条货主档案记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | null>

const session = useSessionStore()
const ENDPOINT = '/api/customer'
const columns = ["客户编码", "客户名称", "客户类型", "联系人", "联系电话", "结算方式", "信用等级", "客户状态", "责任人", "所属部门"]
const statuses = ["待审核", "合作中", "已暂停", "已终止"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const stats = ref([
  { label: "合作货主", value: 0 },
  { label: "待审核货主", value: 0 },
  { label: "停用货主", value: 0 },
])

// 列表里只要存在非本人负责的货主，就提示一次只读规则。
const readonlyHint = computed(() => {
  const blocked = rows.value.some((row) => !canChange(row))
  return blocked ? `当前账号「${session.operator}」对非本人负责的货主仅可查看，不能提交变更。` : ''
})

function canChange(row: Row): boolean {
  return String(row['责任人'] ?? '') === session.operator
}

function availableActions(row: Row): string[] {
  switch (row['客户状态']) {
    case '待审核':
      return ['审核客户', '终止合作']
    case '合作中':
      return ['暂停合作', '终止合作']
    default:
      // 已暂停可恢复合作，已终止为终态不可再操作
      return row['客户状态'] === '已暂停' ? ['审核客户', '终止合作'] : []
  }
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '货主登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  if (!canChange(row)) {
    errorMessage.value = '仅该客户编码对应的责任人可提交变更，当前账号只能查看'
    return
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (response.status === 403) {
      const payload = (await response.json().catch(() => null)) as { detail?: string } | null
      throw new Error(payload?.detail ?? '仅责任人可提交变更，当前账号只能查看')
    }
    if (!response.ok) {
      throw new Error('货主档案动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '货主档案操作失败'
  }
}

async function reloadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) return
    const data = (await response.json()) as Record<string, number>
    stats.value = [
      { label: '合作货主', value: data['合作货主'] ?? 0 },
      { label: '待审核货主', value: data['待审核货主'] ?? 0 },
      { label: '停用货主', value: data['停用货主'] ?? 0 },
    ]
  } catch {
    // 统计读取失败不阻塞列表。
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  if (statusFilter.value) params.set('status', statusFilter.value)
  const query = params.toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('货主列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    await reloadStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '货主档案列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.readonly-hint {
  margin: 8px 0;
  padding: 8px 12px;
  color: #8a6d1d;
  background: #fdf6e3;
  border: 1px solid #ecd9a4;
  border-radius: 6px;
  font-size: 13px;
}

.readonly-tag {
  color: #94a3b8;
  font-size: 12px;
}
</style>
