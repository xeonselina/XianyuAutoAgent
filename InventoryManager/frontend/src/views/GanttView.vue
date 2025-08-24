<template>
  <div class="gantt-view">
    <GanttChart />
  </div>
</template>

<script setup lang="ts">
import GanttChart from '@/components/GanttChart.vue'
</script>

<style scoped>
.gantt-view {
  height: 100vh;
  overflow: hidden;
  position: relative;
}
</style>
