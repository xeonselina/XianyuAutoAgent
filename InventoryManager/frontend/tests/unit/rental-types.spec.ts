/**
 * 租赁类型转换函数单元测试
 */

import { describe, it, expect } from 'vitest'
import {
  convertFormDataToCreatePayload,
  convertRentalToFormData,
  type RentalFormData,
  type Rental
} from '@/types/rental'

describe('Rental Type Conversions', () => {
  describe('convertFormDataToCreatePayload', () => {
    it('should convert UI form data with bundled accessories to API payload', () => {
      const formData: RentalFormData = {
        device_id: 1,
        start_date: '2026-01-10',
        end_date: '2026-01-15',
        customer_name: '测试客户',
        customer_phone: '13800138000',
        destination: '北京市',
        bundled_accessories: ['handle', 'lens_mount'],
        phone_holder_id: null,
        tripod_id: null
      }

      const payload = convertFormDataToCreatePayload(formData)

      expect(payload.includes_handle).toBe(true)
      expect(payload.includes_lens_mount).toBe(true)
      expect(payload.accessories).toEqual([])
      expect(payload.device_id).toBe(1)
      expect(payload.customer_name).toBe('测试客户')
    })

    it('should convert form data with only handle selected', () => {
      const formData: RentalFormData = {
        device_id: 2,
        start_date: '2026-01-10',
        end_date: '2026-01-15',
        customer_name: '客户B',
        bundled_accessories: ['handle'],
        phone_holder_id: null,
        tripod_id: null
      }

      const payload = convertFormDataToCreatePayload(formData)

      expect(payload.includes_handle).toBe(true)
      expect(payload.includes_lens_mount).toBe(false)
    })

    it('should convert form data with inventory accessories', () => {
      const formData: RentalFormData = {
        device_id: 3,
        start_date: '2026-01-10',
        end_date: '2026-01-15',
        customer_name: '客户C',
        bundled_accessories: [],
        phone_holder_id: 101,
        tripod_id: 102
      }

      const payload = convertFormDataToCreatePayload(formData)

      expect(payload.includes_handle).toBe(false)
      expect(payload.includes_lens_mount).toBe(false)
      expect(payload.accessories).toEqual([101, 102])
    })

    it('should convert form data with mixed accessories', () => {
      const formData: RentalFormData = {
        device_id: 4,
        start_date: '2026-01-10',
        end_date: '2026-01-15',
        customer_name: '客户D',
        bundled_accessories: ['handle', 'lens_mount'],
        phone_holder_id: 103,
        tripod_id: null
      }

      const payload = convertFormDataToCreatePayload(formData)

      expect(payload.includes_handle).toBe(true)
      expect(payload.includes_lens_mount).toBe(true)
      expect(payload.accessories).toEqual([103])
    })

    it('should filter out null accessory IDs', () => {
      const formData: RentalFormData = {
        device_id: 5,
        start_date: '2026-01-10',
        end_date: '2026-01-15',
        customer_name: '客户E',
        bundled_accessories: [],
        phone_holder_id: null,
        tripod_id: 104
      }

      const payload = convertFormDataToCreatePayload(formData)

      expect(payload.accessories).toEqual([104])
      expect(payload.accessories).not.toContain(null)
    })
  })

  describe('convertRentalToFormData', () => {
    it('should convert API rental with bundled accessories to form data', () => {
      const rental: Rental = {
        id: 1,
        device_id: 10,
        start_date: '2026-01-10',
        end_date: '2026-01-15',
        customer_name: '测试客户',
        status: 'not_shipped',
        created_at: '2026-01-09T10:00:00Z',
        updated_at: '2026-01-09T10:00:00Z',
        includes_handle: true,
        includes_lens_mount: true,
        accessories: []
      }

      const formData = convertRentalToFormData(rental)

      expect(formData.bundled_accessories).toEqual(['handle', 'lens_mount'])
      expect(formData.phone_holder_id).toBe(null)
      expect(formData.tripod_id).toBe(null)
      expect(formData.device_id).toBe(10)
      expect(formData.customer_name).toBe('测试客户')
    })

    it('should convert rental with only handle', () => {
      const rental: Rental = {
        id: 2,
        device_id: 20,
        start_date: '2026-01-10',
        end_date: '2026-01-15',
        customer_name: '客户F',
        status: 'shipped',
        created_at: '2026-01-09T10:00:00Z',
        updated_at: '2026-01-09T10:00:00Z',
        includes_handle: true,
        includes_lens_mount: false,
        accessories: []
      }

      const formData = convertRentalToFormData(rental)

      expect(formData.bundled_accessories).toEqual(['handle'])
      expect(formData.bundled_accessories).not.toContain('lens_mount')
    })

    it('should convert rental with inventory accessories', () => {
      const rental: Rental = {
        id: 3,
        device_id: 30,
        start_date: '2026-01-10',
        end_date: '2026-01-15',
        customer_name: '客户G',
        status: 'not_shipped',
        created_at: '2026-01-09T10:00:00Z',
        updated_at: '2026-01-09T10:00:00Z',
        includes_handle: false,
        includes_lens_mount: false,
        accessories: [
          {
            id: 201,
            name: '手机支架-P01',
            type: 'phone_holder',
            is_bundled: false,
            serial_number: 'PH-001'
          },
          {
            id: 202,
            name: '三脚架-T01',
            type: 'tripod',
            is_bundled: false,
            serial_number: 'TR-001'
          }
        ]
      }

      const formData = convertRentalToFormData(rental)

      expect(formData.bundled_accessories).toEqual([])
      expect(formData.phone_holder_id).toBe(201)
      expect(formData.tripod_id).toBe(202)
    })

    it('should convert rental with mixed accessories', () => {
      const rental: Rental = {
        id: 4,
        device_id: 40,
        start_date: '2026-01-10',
        end_date: '2026-01-15',
        customer_name: '客户H',
        status: 'shipped',
        created_at: '2026-01-09T10:00:00Z',
        updated_at: '2026-01-09T10:00:00Z',
        includes_handle: true,
        includes_lens_mount: false,
        accessories: [
          {
            id: 203,
            name: '手机支架-P02',
            type: 'phone_holder',
            is_bundled: false
          }
        ]
      }

      const formData = convertRentalToFormData(rental)

      expect(formData.bundled_accessories).toEqual(['handle'])
      expect(formData.phone_holder_id).toBe(203)
      expect(formData.tripod_id).toBe(null)
    })

    it('should handle rental with no accessories', () => {
      const rental: Rental = {
        id: 5,
        device_id: 50,
        start_date: '2026-01-10',
        end_date: '2026-01-15',
        customer_name: '客户I',
        status: 'not_shipped',
        created_at: '2026-01-09T10:00:00Z',
        updated_at: '2026-01-09T10:00:00Z',
        includes_handle: false,
        includes_lens_mount: false,
        accessories: []
      }

      const formData = convertRentalToFormData(rental)

      expect(formData.bundled_accessories).toEqual([])
      expect(formData.phone_holder_id).toBe(null)
      expect(formData.tripod_id).toBe(null)
    })
  })

  describe('Round-trip conversion', () => {
    it('should maintain data integrity through conversion cycles', () => {
      // Start with form data
      const originalFormData: RentalFormData = {
        device_id: 100,
        start_date: '2026-01-10',
        end_date: '2026-01-15',
        customer_name: '往返测试客户',
        bundled_accessories: ['handle', 'lens_mount'],
        phone_holder_id: 301,
        tripod_id: null
      }

      // Convert to API payload
      const payload = convertFormDataToCreatePayload(originalFormData)

      // Simulate API response (rental object)
      const apiRental: Rental = {
        id: 999,
        device_id: payload.device_id,
        start_date: payload.start_date,
        end_date: payload.end_date,
        customer_name: payload.customer_name,
        status: 'not_shipped',
        created_at: '2026-01-09T10:00:00Z',
        updated_at: '2026-01-09T10:00:00Z',
        includes_handle: payload.includes_handle,
        includes_lens_mount: payload.includes_lens_mount,
        accessories: payload.accessories.map(id => ({
          id,
          name: `Accessory-${id}`,
          type: id === 301 ? 'phone_holder' as const : 'tripod' as const,
          is_bundled: false
        }))
      }

      // Convert back to form data
      const convertedFormData = convertRentalToFormData(apiRental)

      // Verify data integrity
      expect(convertedFormData.bundled_accessories).toEqual(originalFormData.bundled_accessories)
      expect(convertedFormData.phone_holder_id).toBe(originalFormData.phone_holder_id)
      expect(convertedFormData.tripod_id).toBe(originalFormData.tripod_id)
      expect(convertedFormData.device_id).toBe(originalFormData.device_id)
      expect(convertedFormData.customer_name).toBe(originalFormData.customer_name)
    })
  })
})
