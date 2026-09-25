const deviceCollator = new Intl.Collator('zh-CN', {
  numeric: true,
  sensitivity: 'base',
})

type SortableDevice = {
  id: number
  name: string
  model?: string
  device_model?: { display_name?: string; name?: string } | null
}

export const compareRentalDevices = (left: SortableDevice, right: SortableDevice) => {
  const leftModel = left.device_model?.display_name || left.device_model?.name || left.model || ''
  const rightModel = right.device_model?.display_name || right.device_model?.name || right.model || ''
  return deviceCollator.compare(leftModel, rightModel)
    || deviceCollator.compare(left.name, right.name)
    || left.id - right.id
}
