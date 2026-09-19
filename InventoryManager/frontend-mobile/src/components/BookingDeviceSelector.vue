<template>
  <van-field :model-value="name" readonly clickable label="选择设备" placeholder="请选择设备" @click="emit('open')">
    <template #button>
      <van-button size="small" type="primary" :loading="loading" :disabled="!canSearch" @click.stop="emit('search')">查找档期</van-button>
    </template>
  </van-field>
</template>
<script setup lang="ts">
defineProps<{ name: string; loading: boolean; canSearch: boolean }>()
const emit = defineEmits<{ open: []; search: [] }>()
</script>
