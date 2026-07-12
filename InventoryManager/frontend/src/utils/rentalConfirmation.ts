import dayjs from 'dayjs'
import { lensComboDisplay } from '@/config/lensCombo'
import type { Rental } from '@/stores/gantt'

export interface RentalConfirmationContent {
  lines: string[]
  text: string
}

const dateOnly = (value?: string | null): string => {
  if (!value) return '未填写'
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('YYYY-MM-DD') : '未填写'
}

const addressWithPhone = (destination?: string, phone?: string): string => {
  const address = destination?.trim() || ''
  const rawPhone = phone?.trim() || ''
  if (!address) return rawPhone || '未填写'
  if (!rawPhone) return address
  const phoneDigits = rawPhone.replace(/\D/g, '')
  const addressDigits = address.replace(/\D/g, '')
  return phoneDigits && addressDigits.includes(phoneDigits)
    ? address
    : `${address}，${rawPhone}`
}

const accessoryLabel = (accessory: NonNullable<Rental['accessories']>[number]): string => {
  const type = accessory.type?.toLowerCase() || ''
  const searchable = `${accessory.name || ''} ${accessory.model || ''}`.toLowerCase()
  if (type === 'phone_holder' || searchable.includes('手机支架') || searchable.includes('phone')) {
    return '手机支架'
  }
  if (type === 'tripod' || searchable.includes('三脚架') || searchable.includes('tripod')) {
    return '三脚架'
  }
  return accessory.name?.trim() || accessory.model?.trim() || ''
}

export const buildRentalConfirmation = (rental: Rental): RentalConfirmationContent => {
  const model = rental.device?.device_model?.display_name
    || rental.device?.device_model?.name
    || rental.device?.model
    || '未识别型号'
  const lens = rental.lens_combo ? lensComboDisplay(rental.lens_combo) : '未填写镜头组合'
  const accessories = new Set<string>()
  if (rental.includes_lens_mount) accessories.add('镜头支架')
  if (rental.includes_handle) accessories.add('手柄')
  for (const accessory of rental.accessories || []) {
    const label = accessoryLabel(accessory)
    if (label) accessories.add(label)
  }
  const accessoryParts = accessories.size ? [...accessories] : ['无附件']
  const lines = [
    `收货地址：${addressWithPhone(rental.destination, rental.customer_phone)}`,
    `寄出时间：${dateOnly(rental.ship_out_time)}`,
    `预计收货：${dateOnly(rental.start_date)}`,
    `客户归还：${dateOnly(rental.end_date)}`,
    `寄出型号：${[model, lens, ...accessoryParts].join(' + ')}`,
  ]
  return { lines, text: lines.join('\n') }
}
