import axios from 'axios'
import { ref } from 'vue'

export interface BookingWarehouse {
  id: number
  name: string
  is_default: boolean
  province: string
  city: string
  district: string
  address_summary: string
}

export interface BookingDeviceModel {
  id: number
  name: string
  display_name: string
  description?: string | null
}

export interface BookingAccessoryType {
  id: number
  name: string
  display_name: string
  tracking_mode: 'device_bound' | 'logical_unit'
  display_order: number
}

export interface BookingBootstrap {
  request_id: string
  evaluated_at: string
  warehouses: BookingWarehouse[]
  recent_warehouse_id: number | null
  default_warehouse_id: number | null
  device_models: BookingDeviceModel[]
  accessory_types: BookingAccessoryType[]
  form_policy: Record<string, unknown>
}

export interface BookingAccessoryAvailability {
  accessory_type_id: number
  name: string
  display_name: string
  tracking_mode: 'device_bound' | 'logical_unit'
  requested: boolean
  total: number | null
  reserved: number | null
  available: number | null
  fulfilled: boolean
  relay_confirmation_required: boolean
  shortage: boolean
  display_hint: string
}

export interface BookingCandidate {
  device: {
    id: number
    name: string
    serial_number?: string | null
    model?: string | null
    model_id: number
    warehouse_id: number
  }
  warehouse: BookingWarehouse
  available: boolean
  hard_conflicts: Array<Record<string, unknown>>
  warnings: Array<Record<string, unknown>>
  relay_candidate: boolean
  logistics_days: number | null
  planned_ship_out_date: string | null
  planned_return_date: string | null
  submission_ready: boolean
  accessories: BookingAccessoryAvailability[]
}

export interface BookingAvailability {
  request_id: string
  evaluated_at: string
  preferred_warehouse_id: number | null
  requested_accessory_type_ids: number[]
  estimate_by_warehouse: Record<string, {
    warehouse_id: number
    status: string
    safe_failure_reason: string | null
    logistics_days: number | null
    manual_confirmation_required: boolean
    confirmation_context: string
  }>
  candidates: BookingCandidate[]
}

export interface BookingAvailabilityPayload {
  start_date: string
  end_date: string
  model_id: number
  preferred_warehouse_id: number | null
  exclude_rental_id?: number
  destination: {
    province: string
    city: string
    district: string
    address_detail: string
  }
  requested_accessory_type_ids: number[]
  manual_logistics_by_warehouse?: Record<string, {
    days: number
    context: string
  }>
}

const unwrap = <T>(response: { data: any }): T => (
  response.data?.data ?? response.data
) as T

export function useRentalBooking() {
  const bootstrap = ref<BookingBootstrap | null>(null)
  const availability = ref<BookingAvailability | null>(null)
  const bootstrapLoading = ref(false)
  const availabilityLoading = ref(false)
  const availabilityFailed = ref(false)
  let bootstrapInFlight: Promise<BookingBootstrap> | null = null
  let availabilityGeneration = 0

  const loadBootstrap = async (): Promise<BookingBootstrap> => {
    if (bootstrapInFlight) return bootstrapInFlight
    bootstrapLoading.value = true
    bootstrapInFlight = axios.get('/api/rental-booking/bootstrap')
      .then(response => {
        const result = unwrap<BookingBootstrap>(response)
        bootstrap.value = result
        return result
      })
      .finally(() => {
        bootstrapLoading.value = false
        bootstrapInFlight = null
      })
    return bootstrapInFlight
  }

  const evaluateAvailability = async (
    payload: BookingAvailabilityPayload,
  ): Promise<BookingAvailability | null> => {
    const generation = ++availabilityGeneration
    availabilityLoading.value = true
    availabilityFailed.value = false
    try {
      const response = await axios.post(
        '/api/rental-booking/availability',
        payload,
      )
      if (generation !== availabilityGeneration) return null
      const result = unwrap<BookingAvailability>(response)
      availability.value = result
      return result
    } catch (error) {
      if (generation === availabilityGeneration) {
        availability.value = null
        availabilityFailed.value = true
      }
      throw error
    } finally {
      if (generation === availabilityGeneration) {
        availabilityLoading.value = false
      }
    }
  }

  const resetAvailability = () => {
    availabilityGeneration += 1
    availability.value = null
    availabilityLoading.value = false
    availabilityFailed.value = false
  }

  return {
    availability,
    availabilityFailed,
    availabilityLoading,
    bootstrap,
    bootstrapLoading,
    evaluateAvailability,
    loadBootstrap,
    resetAvailability,
  }
}
