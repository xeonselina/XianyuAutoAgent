/**
 * 统一时区处理工具
 * 
 * 核心原则：
 * 1. 所有日期计算和比较都使用中国时区(Asia/Shanghai)
 * 2. API传输使用ISO 8601格式
 * 3. 显示时转换为用户本地时区
 */

import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import timezone from 'dayjs/plugin/timezone'

// 启用插件
dayjs.extend(utc)
dayjs.extend(timezone)

// 系统统一时区 - 中国时区
export const SYSTEM_TIMEZONE = 'Asia/Shanghai'

/**
 * 获取当前日期(中国时区)
 */
export const getCurrentDate = (): dayjs.Dayjs => {
  return dayjs().tz(SYSTEM_TIMEZONE)
}

/**
 * 获取今天的日期字符串(YYYY-MM-DD格式，中国时区)
 */
export const getTodayString = (): string => {
  return getCurrentDate().format('YYYY-MM-DD')
}

/**
 * 将任意日期转换为中国时区的日期字符串
 */
export const toSystemDateString = (date: string | Date | dayjs.Dayjs): string => {
  return dayjs(date).tz(SYSTEM_TIMEZONE).format('YYYY-MM-DD')
}

/**
 * 将任意日期转换为中国时区的日期时间字符串
 */
export const toSystemDateTimeString = (date: string | Date | dayjs.Dayjs): string => {
  return dayjs(date).tz(SYSTEM_TIMEZONE).format('YYYY-MM-DD HH:mm:ss')
}

/**
 * 解析日期字符串为dayjs对象(中国时区)
 */
export const parseSystemDate = (dateString: string): dayjs.Dayjs => {
  return dayjs.tz(dateString, SYSTEM_TIMEZONE)
}

/**
 * 将日期转换为API传输格式(ISO 8601)
 */
export const toAPIFormat = (date: string | Date | dayjs.Dayjs): string => {
  return dayjs(date).tz(SYSTEM_TIMEZONE).toISOString()
}

/**
 * 从API格式解析日期
 */
export const fromAPIFormat = (isoString: string): dayjs.Dayjs => {
  return dayjs(isoString).tz(SYSTEM_TIMEZONE)
}

/**
 * 检查两个日期是否在同一天(中国时区)
 */
export const isSameDay = (date1: string | Date | dayjs.Dayjs, date2: string | Date | dayjs.Dayjs): boolean => {
  return dayjs(date1).tz(SYSTEM_TIMEZONE).format('YYYY-MM-DD') === 
         dayjs(date2).tz(SYSTEM_TIMEZONE).format('YYYY-MM-DD')
}

/**
 * 检查日期是否是今天(中国时区)
 */
export const isToday = (date: string | Date | dayjs.Dayjs): boolean => {
  return isSameDay(date, getCurrentDate())
}

/**
 * 生成日期范围数组
 */
export const generateDateRange = (startDate: dayjs.Dayjs, endDate: dayjs.Dayjs): Date[] => {
  const dates: Date[] = []
  let current = startDate.tz(SYSTEM_TIMEZONE)
  const end = endDate.tz(SYSTEM_TIMEZONE)
  
  while (current.isBefore(end) || current.isSame(end, 'day')) {
    dates.push(current.toDate())
    current = current.add(1, 'day')
  }
  
  return dates
}

/**
 * 格式化显示日期(根据用户本地时区)
 */
export const formatDisplayDate = (date: string | Date | dayjs.Dayjs, format = 'YYYY-MM-DD'): string => {
  return dayjs(date).format(format)
}

/**
 * 格式化显示日期时间(根据用户本地时区)
 */
export const formatDisplayDateTime = (date: string | Date | dayjs.Dayjs, format = 'YYYY-MM-DD HH:mm:ss'): string => {
  return dayjs(date).format(format)
}

/**
 * 创建中国时区的日期对象
 */
export const createSystemDate = (year: number, month: number, day: number, hour = 0, minute = 0, second = 0): dayjs.Dayjs => {
  return dayjs.tz(`${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')} ${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:${String(second).padStart(2, '0')}`, SYSTEM_TIMEZONE)
}

/**
 * 日期范围工具类
 */
export class DateRangeUtils {
  static getWeekRange(date: dayjs.Dayjs, weeks: number = 0): { start: dayjs.Dayjs, end: dayjs.Dayjs } {
    const baseDate = date.add(weeks * 7, 'day').tz(SYSTEM_TIMEZONE)
    const start = baseDate.subtract(15, 'day')
    const end = baseDate.add(15, 'day')
    return { start, end }
  }
  
  static getMonthRange(date: dayjs.Dayjs): { start: dayjs.Dayjs, end: dayjs.Dayjs } {
    const baseDate = date.tz(SYSTEM_TIMEZONE)
    const start = baseDate.startOf('month')
    const end = baseDate.endOf('month')
    return { start, end }
  }
}