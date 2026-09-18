<script setup lang="ts">
import {
  Box,
  Connection,
  DocumentChecked,
  Location,
  Right,
} from '@element-plus/icons-vue'


const operationGroups = [
  {
    title: '发货处理',
    description: '集中处理当天及指定日期范围内的待发货订单。',
    items: [
      {
        title: '批量发货',
        description: '预览订单、打印发货单与快递面单，并批量预约寄件。',
        to: '/batch-shipping',
        icon: Box,
        tone: 'blue',
      },
      {
        title: '接力发货',
        description: '管理前后订单之间的设备接力关系与发货状态。',
        to: '/relay-management',
        icon: Connection,
        tone: 'orange',
      },
    ],
  },
  {
    title: '收货与核验',
    description: '设备寄回后完成验货，并跟踪物流状态。',
    items: [
      {
        title: '验货验机',
        description: '开始验货、查看历史记录并处理异常或押金状态。',
        to: '/inspection-records',
        icon: DocumentChecked,
        tone: 'green',
      },
      {
        title: '物流查询',
        description: '查询顺丰运单轨迹，辅助确认寄出与寄回状态。',
        to: '/sf-tracking',
        icon: Location,
        tone: 'violet',
      },
    ],
  },
]
</script>

<template>
  <div class="operations-page">
    <header class="page-heading">
      <div>
        <span class="page-kicker">OPERATIONS</span>
        <h1>收货发货</h1>
        <p>按业务阶段进入对应工作区，减少在档期页面里来回寻找操作。</p>
      </div>
    </header>

    <section
      v-for="group in operationGroups"
      :key="group.title"
      class="operation-group"
    >
      <div class="group-heading">
        <h2>{{ group.title }}</h2>
        <p>{{ group.description }}</p>
      </div>
      <div class="operation-grid">
        <RouterLink
          v-for="item in group.items"
          :key="item.title"
          :to="item.to"
          class="operation-card"
          :data-testid="`operation-${item.to.slice(1)}`"
        >
          <span class="operation-icon" :class="`tone-${item.tone}`">
            <el-icon><component :is="item.icon" /></el-icon>
          </span>
          <span class="operation-copy">
            <strong>{{ item.title }}</strong>
            <small>{{ item.description }}</small>
          </span>
          <el-icon class="operation-arrow"><Right /></el-icon>
        </RouterLink>
      </div>
    </section>
  </div>
</template>

<style scoped>
.operations-page {
  min-height: 100%;
  padding: 28px clamp(20px, 4vw, 56px) 48px;
  color: #101828;
  background: #f7f9fc;
}

.page-heading,
.operation-group {
  max-width: 1120px;
  margin: 0 auto;
}

.page-heading {
  padding: 22px 0 28px;
}

.page-kicker { color: #2e90fa; font-size: 11px; font-weight: 800; letter-spacing: .14em; }
.page-heading h1 { margin: 5px 0 6px; font-size: 30px; letter-spacing: -.03em; }
.page-heading p, .group-heading p { margin: 0; color: #667085; font-size: 14px; }
.operation-group + .operation-group { margin-top: 34px; }
.group-heading { margin-bottom: 14px; }
.group-heading h2 { margin: 0 0 4px; font-size: 17px; }
.operation-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.operation-card { display: grid; grid-template-columns: 44px minmax(0, 1fr) auto; align-items: center; gap: 14px; min-height: 104px; padding: 18px; border: 1px solid #e4e7ec; border-radius: 12px; color: inherit; background: #fff; box-shadow: 0 1px 2px rgb(16 24 40 / 4%); text-decoration: none; transition: transform .16s ease, border-color .16s ease, box-shadow .16s ease; }
.operation-card:hover { transform: translateY(-2px); border-color: #b2ccff; box-shadow: 0 8px 22px rgb(16 24 40 / 9%); }
.operation-icon { display: grid; width: 44px; height: 44px; place-items: center; border-radius: 10px; font-size: 21px; }
.tone-blue { color: #175cd3; background: #eff4ff; }
.tone-orange { color: #b54708; background: #fff4e8; }
.tone-green { color: #027a48; background: #ecfdf3; }
.tone-violet { color: #6941c6; background: #f4f3ff; }
.operation-copy { display: grid; gap: 5px; }
.operation-copy strong { font-size: 16px; }
.operation-copy small { color: #667085; font-size: 13px; line-height: 1.55; }
.operation-arrow { color: #98a2b3; }

@media (max-width: 720px) {
  .operations-page { padding: 18px 14px 32px; }
  .operation-grid { grid-template-columns: 1fr; }
}
</style>
