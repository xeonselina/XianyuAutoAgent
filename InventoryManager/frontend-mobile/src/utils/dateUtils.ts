/**
 * 简化的日期处理工具
 * 
 * 核心原则：
 * 1. 前端、后端、数据库都使用本地时区时间
 * 2. 不进行任何时区转换
 * 3. 使用简单的日期字符串格式进行传输
 */

import dayjs from 'dayjs'

/**
 * 获取当前日期
 */
export const getCurrentDate = (): dayjs.Dayjs => {
  return dayjs()
}

/**
 * 获取今天的日期字符串(YYYY-MM-DD格式)
 */
export const getTodayString = (): string => {
  return dayjs().format('YYYY-MM-DD')
}

/**
 * 将日期转换为日期字符串
 */
export const toDateString = (date: string | Date | dayjs.Dayjs): string => {
  return dayjs(date).format('YYYY-MM-DD')
}

/**
 * 将日期转换为日期时间字符串
 */
export const toDateTimeString = (date: string | Date | dayjs.Dayjs): string => {
  return dayjs(date).format('YYYY-MM-DD HH:mm:ss')
}

/**
 * 解析日期字符串为dayjs对象
 */
export const parseDate = (dateString: string): dayjs.Dayjs => {
  return dayjs(dateString)
}

/**
 * 将日期转换为API传输格式 (ISO 8601 本地时间)
 */
export const toAPIFormat = (date: string | Date | dayjs.Dayjs): string => {
  return dayjs(date).format('YYYY-MM-DDTHH:mm:ss')
}

/**
 * 从API格式解析日期
 */
export const fromAPIFormat = (dateString: string): dayjs.Dayjs => {
  return dayjs(dateString)
}

/**
 * 检查两个日期是否在同一天
 */
export const isSameDay = (date1: string | Date | dayjs.Dayjs, date2: string | Date | dayjs.Dayjs): boolean => {
  return dayjs(date1).format('YYYY-MM-DD') === dayjs(date2).format('YYYY-MM-DD')
}

/**
 * 检查日期是否是今天
 */
export const isToday = (date: string | Date | dayjs.Dayjs): boolean => {
  return isSameDay(date, getCurrentDate())
}

/**
 * 生成日期范围数组
 */
export const generateDateRange = (startDate: dayjs.Dayjs, endDate: dayjs.Dayjs): Date[] => {
  const dates: Date[] = []
  let current = startDate
  const end = endDate
  
  while (current.isBefore(end) || current.isSame(end, 'day')) {
    dates.push(current.toDate())
    current = current.add(1, 'day')
  }
  
  return dates
}

/**
 * 格式化显示日期
 */
export const formatDisplayDate = (date: string | Date | dayjs.Dayjs, format = 'YYYY-MM-DD'): string => {
  return dayjs(date).format(format)
}

/**
 * 格式化显示日期时间
 */
export const formatDisplayDateTime = (date: string | Date | dayjs.Dayjs, format = 'YYYY-MM-DD HH:mm:ss'): string => {
  return dayjs(date).format(format)
}

/**
 * 创建日期对象
 */
export const createDate = (year: number, month: number, day: number, hour = 0, minute = 0, second = 0): dayjs.Dayjs => {
  return dayjs(`${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')} ${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:${String(second).padStart(2, '0')}`)
}

/**
 * 日期范围工具类
 */
export class DateRangeUtils {
  static getWeekRange(date: dayjs.Dayjs, weeks: number = 0): { start: dayjs.Dayjs, end: dayjs.Dayjs } {
    const baseDate = date.add(weeks * 7, 'day')
    const start = baseDate.subtract(15, 'day')
    const end = baseDate.add(15, 'day')
    return { start, end }
  }
  
  static getMonthRange(date: dayjs.Dayjs): { start: dayjs.Dayjs, end: dayjs.Dayjs } {
    const baseDate = date
    const start = baseDate.startOf('month')
    const end = baseDate.endOf('month')
    return { start, end }
  }
}

// 向后兼容的别名
export const toSystemDateString = toDateString
export const toDateStringFromDB = toDateString
export const parseSystemDate = parseDate
export const toSystemDateTimeString = toDateTimeString