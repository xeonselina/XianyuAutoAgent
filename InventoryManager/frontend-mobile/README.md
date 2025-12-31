# 库存管理系统 - 移动端前端

基于 Vue 3 + TypeScript + Vant 4 的移动端前端应用。

## 技术栈

- **框架**: Vue 3.5 + TypeScript 5.9
- **UI 组件库**: Vant 4.9
- **状态管理**: Pinia 3.0
- **路由**: Vue Router 4.6
- **构建工具**: Vite 7.2
- **HTTP 客户端**: Axios 1.13
- **日期处理**: Day.js 1.11

## 功能特性

### 1. 设备档期查看 (甘特图)
- 📅 简化的时间轴展示,显示设备租赁情况
- 🔍 搜索设备和客户名称
- 📆 日期导航(上一周/下一周/今天)
- 👆 点击租赁块查看详细信息
- 🔄 下拉刷新数据

### 2. 快速预约档期
- 🎯 选择设备进行预约
- 📆 日期选择器(开始/结束日期)
- 📝 填写客户信息(姓名/电话/目的地)
- 💰 可选填写闲鱼订单号和金额
- ✅ 冲突检测和提醒

### 3. 响应式设计
- 📱 适配各种移动设备屏幕
- 👆 触摸优化的交互体验
- 🎨 现代化的移动端 UI

## 项目结构

```
frontend-mobile/
├── src/
│   ├── api/                 # API 服务层
│   │   ├── client.ts        # Axios 实例配置
│   │   ├── device.ts        # 设备相关 API
│   │   ├── rental.ts        # 租赁相关 API
│   │   └── gantt.ts         # 甘特图相关 API
│   ├── stores/              # Pinia 状态管理
│   │   └── gantt.ts         # 甘特图 Store
│   ├── views/               # 页面组件
│   │   ├── GanttView.vue    # 设备档期页面
│   │   └── BookingView.vue  # 预约页面
│   ├── types/               # TypeScript 类型定义
│   │   └── index.ts         # 通用类型
│   ├── utils/               # 工具函数
│   │   ├── date.ts          # 日期处理
│   │   └── validation.ts    # 表单验证
│   ├── router/              # 路由配置
│   │   └── index.ts
│   ├── App.vue              # 根组件
│   └── main.ts              # 应用入口
├── public/                  # 静态资源
├── .env.development         # 开发环境配置
├── .env.production          # 生产环境配置
├── vite.config.ts           # Vite 配置
├── tsconfig.json            # TypeScript 配置
└── package.json             # 依赖配置
```

## 开发指南

### 环境要求

- Node.js >= 18.x
- npm >= 9.x

### 安装依赖

```bash
cd frontend-mobile
npm install
```

### 开发模式

启动开发服务器(默认端口 5174):

```bash
npm run dev
```

访问: http://localhost:5174

**注意**: 确保后端服务运行在 `http://localhost:5000`

### 生产构建

```bash
npm run build
```

构建产物输出到 `dist/` 目录。

### 预览生产构建

```bash
npm run preview
```

### 运行测试

```bash
npm run test
```

使用 UI 界面运行测试:

```bash
npm run test:ui
```

## API 配置

### 开发环境

API 请求通过 Vite 代理转发到后端:

```typescript
// vite.config.ts
server: {
  port: 5174,
  proxy: {
    '/api': {
      target: 'http://localhost:5000',
      changeOrigin: true
    }
  }
}
```

### 生产环境

生产环境下,需要配置 Nginx 反向代理或修改 `.env.production`:

```bash
VITE_API_BASE_URL=https://your-api-domain.com/api
```

## 数据模型

### Device (设备)
```typescript
interface Device {
  id: number
  name: string
  serial_number: string
  model: string
  model_id: number | null
  is_accessory: boolean
  status: 'online' | 'offline'
  created_at: string
  updated_at: string
}
```

### Rental (租赁记录)
```typescript
interface Rental {
  id: number
  device_id: number
  start_date: string
  end_date: string
  ship_out_time: string | null
  ship_in_time: string | null
  customer_name: string
  customer_phone: string | null
  destination: string | null
  xianyu_order_no: string | null
  order_amount: number | null
  status: RentalStatus
  created_at: string
  updated_at: string
}
```

## 部署

### 1. 构建应用

```bash
npm run build
```

### 2. 部署到 Web 服务器

将 `dist/` 目录的内容部署到 Nginx、Apache 或其他 Web 服务器。

### 3. Nginx 配置示例

```nginx
server {
  listen 80;
  server_name your-domain.com;
  
  root /path/to/frontend-mobile/dist;
  index index.html;
  
  location / {
    try_files $uri $uri/ /index.html;
  }
  
  location /api {
    proxy_pass http://localhost:5000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
  }
}
```

## 浏览器兼容性

- Chrome >= 90
- Safari >= 14
- iOS Safari >= 14
- Android WebView >= 90

## 性能优化

- ✅ 组件懒加载
- ✅ Vant 组件按需引入
- ✅ 路由懒加载
- ✅ 图片懒加载(可选)
- ✅ Gzip 压缩

## 开发规范

### 代码风格

- 使用 TypeScript 严格模式
- 遵循 Vue 3 Composition API 最佳实践
- 使用 ESLint + Prettier 进行代码格式化

### 提交规范

```
feat: 新功能
fix: 修复bug
docs: 文档更新
style: 代码格式调整
refactor: 重构
test: 测试相关
chore: 构建/工具链相关
```

## 常见问题

### 1. API 请求失败

检查后端服务是否启动:
```bash
curl http://localhost:5000/api/devices
```

### 2. 开发服务器端口冲突

修改 `vite.config.ts` 中的端口配置:
```typescript
server: {
  port: 5175  // 改为其他端口
}
```

### 3. 构建后页面空白

检查 `base` 配置和路由模式:
```typescript
// vite.config.ts
export default defineConfig({
  base: './'  // 使用相对路径
})
```

## 许可证

MIT

## 联系方式

如有问题或建议,请联系开发团队。
