/**
 * 日期工具函数
 */

import dayjs from 'dayjs'

/**
 * 格式化日期为YYYY-MM-DD
 */
export const formatDate = (date: Date | string): string => {
  return dayjs(date).format('YYYY-MM-DD')
}

/**
 * 格式化日期时间为YYYY-MM-DD HH:mm:ss
 */
export const formatDateTime = (date: Date | string): string => {
  return dayjs(date).format('YYYY-MM-DD HH:mm:ss')
}

/**
 * 获取当前日期
 */
export const getCurrentDate = (): Date => {
  return new Date()
}

/**
 * 获取当前周的开始和结束日期
 */
export const getCurrentWeek = (): { start: Date; end: Date } => {
  const today = dayjs()
  const start = today.startOf('week')
  const end = today.endOf('week')
  return {
    start: start.toDate(),
    end: end.toDate()
  }
}

/**
 * 添加天数
 */
export const addDays = (date: Date, days: number): Date => {
  return dayjs(date).add(days, 'day').toDate()
}

/**
 * 添加周数
 */
export const addWeeks = (date: Date, weeks: number): Date => {
  return dayjs(date).add(weeks, 'week').toDate()
}

/**
 * 计算两个日期之间的天数
 */
export const diffDays = (date1: Date | string, date2: Date | string): number => {
  return dayjs(date1).diff(dayjs(date2), 'day')
}
