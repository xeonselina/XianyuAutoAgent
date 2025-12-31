/**
 * 表单验证工具函数
 */

/**
 * 验证手机号格式
 */
export const validatePhone = (phone: string): boolean => {
  const phoneReg = /^1[3-9]\d{9}$/
  return phoneReg.test(phone)
}

/**
 * 验证必填字段
 */
export const validateRequired = (value: string | number | null | undefined): boolean => {
  if (value === null || value === undefined) {
    return false
  }
  if (typeof value === 'string') {
    return value.trim().length > 0
  }
  return true
}

/**
 * 验证日期范围(结束日期必须晚于开始日期)
 */
export const validateDateRange = (startDate: string, endDate: string): boolean => {
  return new Date(endDate) > new Date(startDate)
}

/**
 * 验证最小长度
 */
export const validateMinLength = (value: string, minLength: number): boolean => {
  return value.trim().length >= minLength
}
