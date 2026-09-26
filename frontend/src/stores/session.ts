import { defineStore } from 'pinia'

export interface Account {
  /** 登录账号，仅允许 ASCII，作为请求头与后端责任账号比对 */
  operator: string
  /** 责任人姓名，仅用于界面展示 */
  name: string
  department: string
  label: string
}

/** 演示账号：前三位分别是对应客户编码的责任人，值班管理员不归属任何货主，只能查看。 */
export const ACCOUNTS: Account[] = [
  { operator: 'admin', name: '值班管理员', department: '调度室', label: '值班管理员（调度室·只读）' },
  { operator: 'wangmin', name: '王敏', department: '商务一部', label: '王敏（商务一部·CUST-0001 责任人）' },
  { operator: 'lihua', name: '李华', department: '商务一部', label: '李华（商务一部·CUST-0002 责任人）' },
  { operator: 'zhaoqiang', name: '赵强', department: '商务二部', label: '赵强（商务二部·CUST-0003 责任人）' },
]

export const useSessionStore = defineStore('session', {
  state: () => ({
    operator: 'admin',
    name: '值班管理员',
    department: '调度室',
    shiftLabel: '白班 08:00-20:00',
    scope: '港口集装箱作业调度平台',
  }),
  getters: {
    canOperate: (state) => state.operator.length > 0,
  },
  actions: {
    setShift(label: string) {
      this.shiftLabel = label
    },
    switchAccount(loginAccount: string) {
      const account = ACCOUNTS.find((item) => item.operator === loginAccount) ?? ACCOUNTS[0]
      this.operator = account.operator
      this.name = account.name
      this.department = account.department
    },
  },
})
