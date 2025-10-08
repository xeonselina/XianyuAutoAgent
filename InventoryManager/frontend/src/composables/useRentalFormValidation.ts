/**
 * 租赁表单验证组合式函数
 * 提供统一的表单验证规则
 */
import type { FormRules } from 'element-plus'

/**
 * 获取创建租赁的表单验证规则
 */
export function getCreateRentalRules(): FormRules {
  return {
    startDate: [
      { required: true, message: '请选择开始日期', trigger: 'change' }
    ],
    endDate: [
      { required: true, message: '请选择结束日期', trigger: 'change' }
    ],
    logisticsDays: [
      { required: true, message: '请输入物流天数', trigger: 'change' }
    ],
    customerName: [
      { required: true, message: '请输入闲鱼ID', trigger: 'blur' }
    ],
    customerPhone: [
      { pattern: /^1[3-9]\d{9}$/, message: '请输入正确的手机号码', trigger: 'blur' }
    ],
    destination: [
      // 收件信息改为非必填
    ]
  }
}

/**
 * 获取编辑租赁的表单验证规则
 */
export function getEditRentalRules(): FormRules {
  return {
    deviceId: [
      { required: true, message: '请选择设备', trigger: 'change' }
    ],
    endDate: [
      { required: true, message: '请选择结束日期', trigger: 'change' }
    ],
    customerPhone: [
      { pattern: /^1[3-9]\d{9}$/, message: '请输入正确的手机号码', trigger: 'blur' }
    ]
  }
}

/**
 * 验证日期范围
 */
export function validateDateRange(startDate: Date | null, endDate: Date | null): boolean {
  if (!startDate || !endDate) return false
  return endDate >= startDate
}

/**
 * 验证手机号码
 */
export function validatePhone(phone: string): boolean {
  const phoneRegex = /^1[3-9]\d{9}$/
  return phoneRegex.test(phone)
}
