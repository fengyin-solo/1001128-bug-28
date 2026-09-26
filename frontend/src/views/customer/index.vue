<template>
  <section class="page" data-module="customer">
    <header class="page-head">
      <div>
        <h2>货主档案管理</h2>
        <p class="page-desc">按客户编码维护货主档案；只有客户编码对应的责任人可以提交变更，其他账号仅可查看。</p>
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
        <select v-model="status">
          <option value="">全部状态</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

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
            <button class="link" type="button" @click="openDetail(row)">详情</button>
            <template v-if="canEdit(row)">
              <button
                v-for="action in actions"
                :key="action"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </template>
            <span v-else class="readonly-hint">仅查看</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无货主档案数据，可先登记货主</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条货主档案记录（同一客户编码只计一条）</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="detail" class="modal-mask" @click.self="closeDetail">
      <div class="modal">
        <header class="modal-head">
          <h3>货主详情 · {{ detail['客户编码'] }}</h3>
          <button class="link" type="button" @click="closeDetail">关闭</button>
        </header>
        <p v-if="!detailEditable" class="readonly-banner">
          当前账号 {{ session.name }}（{{ session.operator }}）不是该货主责任人（责任人：{{ detail['责任人'] || '—' }} / {{ detail['责任账号'] || '—' }}），仅可查看。
        </p>
        <div class="detail-grid">
          <label>
            <span>客户编码</span>
            <input :value="detail['客户编码']" disabled />
          </label>
          <label>
            <span>客户状态</span>
            <input :value="detail['客户状态']" disabled />
          </label>
          <label>
            <span>责任人</span>
            <input :value="detail['责任人']" disabled />
          </label>
          <label>
            <span>责任部门</span>
            <input :value="detail['责任部门']" disabled />
          </label>
          <label v-for="field in editableFields" :key="field">
            <span>{{ field }}</span>
            <select v-if="field === '信用等级'" v-model="form[field]" :disabled="!detailEditable">
              <option v-for="level in creditLevels" :key="level" :value="level">{{ level }} 级</option>
            </select>
            <input v-else v-model="form[field]" :disabled="!detailEditable" />
          </label>
        </div>
        <footer class="modal-foot">
          <span v-if="formError" class="error-text">{{ formError }}</span>
          <button
            v-if="detailEditable"
            class="btn primary"
            type="button"
            :disabled="saving"
            @click="saveDetail"
          >
            {{ saving ? '提交中…' : '提交变更' }}
          </button>
        </footer>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { readError, request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | boolean | null>

const ENDPOINT = '/api/customer'
const columns = ["客户编码", "客户名称", "客户类型", "联系人", "联系电话", "结算方式", "信用等级", "客户状态", "责任人", "责任账号", "责任部门"]
const actions = ["审核客户", "暂停合作", "终止合作"]
const statuses = ["待审核", "合作中", "已暂停", "已终止"]
const editableFields = ["客户名称", "客户类型", "联系人", "联系电话", "结算方式", "信用等级"]
const creditLevels = ["A", "B", "C", "D"]

const session = useSessionStore()
const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const status = ref('')
const stats = ref([
  { label: '合作货主', value: 0 },
  { label: '待审核货主', value: 0 },
  { label: '已停用货主', value: 0 },
])

const detail = ref<Row | null>(null)
const form = ref<Record<string, string>>({})
const formError = ref('')
const saving = ref(false)

const detailEditable = computed(() =>
  detail.value !== null && String(detail.value['责任账号'] ?? '') === session.operator,
)

function canEdit(row: Row) {
  return String(row['责任账号'] ?? '') === session.operator
}

function resetFilters() {
  keyword.value = ''
  status.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '货主登记入口尚未接入审批流'
}

function openDetail(row: Row) {
  formError.value = ''
  detail.value = row
  form.value = Object.fromEntries(editableFields.map((field) => [field, String(row[field] ?? '')]))
}

function closeDetail() {
  detail.value = null
  formError.value = ''
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error(await readError(response, '货主档案动作未生效，请稍后重试'))
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '货主档案操作失败'
  }
}

async function saveDetail() {
  if (!detail.value) {
    return
  }
  formError.value = ''
  saving.value = true
  try {
    const response = await request(`${ENDPOINT}/${detail.value.id}`, {
      method: 'PUT',
      body: JSON.stringify({ values: { ...form.value } }),
    })
    if (!response.ok) {
      throw new Error(await readError(response, '货主档案变更未生效，请稍后重试'))
    }
    closeDetail()
    await reload()
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '货主档案变更失败'
  } finally {
    saving.value = false
  }
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) {
      return
    }
    const payload = (await response.json()) as Record<string, number>
    stats.value = [
      { label: '合作货主', value: payload['合作中'] ?? 0 },
      { label: '待审核货主', value: payload['待审核'] ?? 0 },
      { label: '已停用货主', value: payload['停用'] ?? 0 },
    ]
  } catch {
    // 统计失败不阻塞列表，卡片保持 0
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) {
    query.set('keyword', keyword.value)
  }
  if (status.value) {
    query.set('status', status.value)
  }
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error(await readError(response, '货主列表读取失败'))
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    // 列表刷新后同步已打开的详情，保证详情与列表同源不错位
    if (detail.value) {
      const latest = rows.value.find((row) => String(row.id) === String(detail.value?.id))
      if (latest) {
        detail.value = latest
      }
    }
    await loadStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '货主档案列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.readonly-hint {
  color: var(--muted);
  font-size: 12px;
}
.filter-item select {
  padding: 4px 6px;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal {
  width: 560px;
  max-width: calc(100vw - 32px);
  background: #fff;
  border-radius: 10px;
  padding: 16px 18px;
}
.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.modal-head h3 {
  margin: 0;
  font-size: 15px;
}
.readonly-banner {
  margin: 0 0 10px;
  padding: 8px 10px;
  border-radius: 6px;
  background: #fef3c7;
  color: #92400e;
  font-size: 12px;
}
.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 12px;
}
.detail-grid label span {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 2px;
}
.detail-grid input,
.detail-grid select {
  width: 100%;
  padding: 5px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
}
.detail-grid input:disabled {
  background: #f1f5f9;
  color: #475569;
}
.modal-foot {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
}
</style>
