import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import axios from 'axios'
import {
  createMemoryHistory,
  createRouter,
  type RouteRecordRaw,
} from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, nextTick } from 'vue'

import App from '@/App.vue'
import { useAuthStore } from '@/stores/auth'
import AccessRestrictedView from '@/views/AccessRestrictedView.vue'
import LoginView from '@/views/LoginView.vue'
import PlatformLoginView from '@/views/PlatformLoginView.vue'
import PlatformTenantsView from '@/views/PlatformTenantsView.vue'
import { installAuthGuards } from '@/router'
import { createMobileAuthGuard } from '../../../frontend-mobile/src/stores/auth'


const apiMocks = vi.hoisted(() => ({
  createTenant: vi.fn(),
  fetchPlatformSession: vi.fn(),
  fetchTenantSession: vi.fn(),
  listTenants: vi.fn(),
  loginPlatform: vi.fn(),
  logoutPlatformSession: vi.fn(),
  logoutTenantSession: vi.fn(),
  patchTenant: vi.fn(),
  requestTenantCode: vi.fn(),
  retryTenant: vi.fn(),
  verifyTenantCode: vi.fn(),
}))

vi.mock('@/api/auth', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/auth')>(),
  ...apiMocks,
}))

const EmptyView = defineComponent({ template: '<div />' })

const tenantData = (accessStatus = 'active', role = 'admin') => ({
  csrf_token: 'tenant-csrf',
  member: {
    id: 7,
    phone: '+8613800138000',
    role,
    status: 'active',
  },
  tenant: {
    id: 3,
    name: '测试租户',
    status: accessStatus === 'suspended' ? 'suspended' : 'active',
    provisioning_status: 'active',
    expires_at: '2026-09-30T00:00:00Z',
    access_status: accessStatus,
  },
})

const platformData = {
  csrf_token: 'platform-csrf',
  admin: { id: 1, username: 'root-admin' },
}

const guardedRoutes: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: EmptyView, meta: { public: true } },
  {
    path: '/access-restricted',
    name: 'access-restricted',
    component: EmptyView,
    meta: { requiresTenant: true },
  },
  {
    path: '/business',
    name: 'business',
    component: EmptyView,
    meta: { requiresTenant: true },
  },
  {
    path: '/settings',
    name: 'settings',
    component: EmptyView,
    meta: { requiresTenant: true },
  },
  {
    path: '/platform/login',
    name: 'platform-login',
    component: EmptyView,
    meta: { public: true, platform: true },
  },
  {
    path: '/platform/tenants',
    name: 'platform-tenants',
    component: EmptyView,
    meta: { platform: true },
  },
]

const makeGuardedRouter = (auth: Record<string, unknown>) => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: guardedRoutes,
  })
  installAuthGuards(router, () => auth as never)
  return router
}

describe('tenant navigation', () => {
  it('redirects an unauthenticated business route to login with the complete next path', async () => {
    const auth = {
      bootstrap: vi.fn().mockResolvedValue(false),
      bootstrapPlatform: vi.fn(),
      authenticated: false,
      platformAuthenticated: false,
    }
    const router = makeGuardedRouter(auth)

    await router.push('/business?day=2026-08-25')
    await router.isReady()

    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.next).toBe('/business?day=2026-08-25')
  })

  it.each(['expired', 'suspended'])(
    'redirects an authenticated %s tenant to the restricted page',
    async (accessStatus) => {
      const auth = {
        bootstrap: vi.fn().mockResolvedValue(true),
        bootstrapPlatform: vi.fn(),
        authenticated: true,
        accessStatus,
        member: { role: 'admin' },
        platformAuthenticated: false,
      }
      const router = makeGuardedRouter(auth)

      await router.push('/business')
      await router.isReady()

      expect(router.currentRoute.value.name).toBe('access-restricted')
      expect(router.currentRoute.value.query.reason).toBe(accessStatus)
    },
  )

  it('blocks an Operator from the settings route', async () => {
    const auth = {
      bootstrap: vi.fn().mockResolvedValue(true),
      bootstrapPlatform: vi.fn(),
      authenticated: true,
      accessStatus: 'active',
      member: { role: 'operator' },
      platformAuthenticated: false,
    }
    const router = makeGuardedRouter(auth)

    await router.push('/settings')
    await router.isReady()

    expect(router.currentRoute.value.name).toBe('access-restricted')
    expect(router.currentRoute.value.query.reason).toBe('forbidden')
  })

  it('checks only the independent platform session for platform routes', async () => {
    const auth = {
      bootstrap: vi.fn(),
      bootstrapPlatform: vi.fn().mockResolvedValue(false),
      authenticated: true,
      accessStatus: 'active',
      member: { role: 'admin' },
      platformAuthenticated: false,
    }
    const router = makeGuardedRouter(auth)

    await router.push('/platform/tenants')
    await router.isReady()

    expect(auth.bootstrap).not.toHaveBeenCalled()
    expect(auth.bootstrapPlatform).toHaveBeenCalledOnce()
    expect(router.currentRoute.value.name).toBe('platform-login')
    expect(router.currentRoute.value.query.next).toBe('/platform/tenants')
  })

  it('sends an unauthenticated mobile visit to the desktop login with its mobile next path', async () => {
    const assign = vi.fn()
    const guard = createMobileAuthGuard(
      vi.fn().mockResolvedValue(false),
      assign,
    )

    const result = await guard({ fullPath: '/edit-rental/9?source=scan' })

    expect(result).toBe(false)
    expect(assign).toHaveBeenCalledWith(
      '/login?next=%2Fmobile%2Fedit-rental%2F9%3Fsource%3Dscan',
    )
  })
})

describe('tenant auth store and login form', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('keeps tenant and platform CSRF values in memory without browser storage', async () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    apiMocks.verifyTenantCode.mockResolvedValue(tenantData())
    apiMocks.fetchPlatformSession.mockResolvedValue(platformData)
    const auth = useAuthStore()

    await auth.verifyCode('13800138000', '123456')
    await auth.bootstrapPlatform()

    expect(auth.csrfToken).toBe('tenant-csrf')
    expect(auth.platformCsrfToken).toBe('platform-csrf')
    expect(axios.defaults.headers.common['X-CSRF-Token']).toBe('tenant-csrf')
    expect(setItem).not.toHaveBeenCalled()
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })

  it('submits the SMS form and returns to a safe next route after verification', async () => {
    apiMocks.requestTenantCode.mockResolvedValue(undefined)
    apiMocks.verifyTenantCode.mockResolvedValue(tenantData())
    const pinia = createPinia()
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/login', component: LoginView },
        { path: '/business', component: EmptyView },
      ],
    })
    await router.push('/login?next=/business')
    await router.isReady()
    const wrapper = mount(LoginView, {
      global: { plugins: [pinia, router] },
    })

    await wrapper.get('[data-testid="phone"]').setValue('13800138000')
    await wrapper.get('[data-testid="request-code"]').trigger('click')
    expect(apiMocks.requestTenantCode).toHaveBeenCalledWith('13800138000')
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="code"]').exists()).toBe(true)
    })

    await wrapper.get('[data-testid="code"]').setValue('123456')
    await wrapper.get('form').trigger('submit')
    await vi.waitFor(() => expect(apiMocks.verifyTenantCode).toHaveBeenCalledOnce())

    expect(apiMocks.verifyTenantCode).toHaveBeenCalledWith(
      '13800138000',
      '123456',
    )
    await vi.waitFor(() => {
      expect(router.currentRoute.value.fullPath).toBe('/business')
    })
  })

  it('explains an expired tenant without exposing business content', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    useAuthStore().applyTenantSession(tenantData('expired'))
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/access-restricted', component: AccessRestrictedView }],
    })
    await router.push('/access-restricted?reason=expired')
    await router.isReady()

    const wrapper = mount(AccessRestrictedView, {
      global: { plugins: [pinia, router] },
    })

    expect(wrapper.text()).toContain('租户已到期')
    expect(wrapper.text()).toContain('业务数据仍会保留')
  })
})

describe('authenticated shell and platform tenant actions', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('does not show the settings entry to an Operator', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.applyTenantSession(tenantData('active', 'operator'))
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', component: EmptyView, meta: { requiresTenant: true } }],
    })
    await router.push('/')
    await router.isReady()

    const wrapper = mount(App, { global: { plugins: [pinia, router] } })

    expect(wrapper.text()).toContain('测试租户')
    expect(wrapper.find('[data-testid="settings-link"]').exists()).toBe(false)
  })

  it('uses username, password and TOTP then returns to the platform next route', async () => {
    apiMocks.loginPlatform.mockResolvedValue(platformData)
    const pinia = createPinia()
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/platform/login', component: PlatformLoginView },
        { path: '/platform/tenants', component: EmptyView },
      ],
    })
    await router.push('/platform/login?next=/platform/tenants')
    await router.isReady()
    const wrapper = mount(PlatformLoginView, {
      global: { plugins: [pinia, router] },
    })

    await wrapper.get('[data-testid="platform-username"]').setValue('root-admin')
    await wrapper.get('[data-testid="platform-password"]').setValue('password')
    await wrapper.get('[data-testid="platform-totp"]').setValue('123456')
    await wrapper.get('form').trigger('submit')
    await vi.waitFor(() => expect(apiMocks.loginPlatform).toHaveBeenCalledOnce())

    expect(apiMocks.loginPlatform).toHaveBeenCalledWith(
      'root-admin',
      'password',
      '123456',
    )
    await vi.waitFor(() => {
      expect(router.currentRoute.value.fullPath).toBe('/platform/tenants')
    })
  })

  it('creates, updates, suspends, resumes and retries tenants with platform CSRF', async () => {
    const tenant = {
      id: 8,
      name: '租户甲',
      status: 'active',
      expires_at: '2026-09-30T00:00:00Z',
      db_name: 'inventory_tenant_00000008',
      provisioning_status: 'failed',
      provisioning_error: 'migration failed',
      admin_phone: '+8613800138000',
    }
    apiMocks.listTenants.mockResolvedValue([tenant])
    apiMocks.createTenant.mockResolvedValue({ ...tenant, id: 9 })
    apiMocks.patchTenant.mockImplementation(
      async (_id: number, patch: Record<string, unknown>) => ({ ...tenant, ...patch }),
    )
    apiMocks.retryTenant.mockResolvedValue({
      ...tenant,
      provisioning_status: 'active',
      provisioning_error: null,
    })
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.applyPlatformSession(platformData)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', component: PlatformTenantsView }],
    })
    await router.push('/')
    await router.isReady()
    const wrapper = mount(PlatformTenantsView, {
      global: { plugins: [pinia, router] },
    })
    await vi.waitFor(() => expect(apiMocks.listTenants).toHaveBeenCalledOnce())
    await nextTick()

    await wrapper.get('[data-testid="new-tenant"]').trigger('click')
    await wrapper.get('[data-testid="tenant-name"]').setValue('租户乙')
    await wrapper.get('[data-testid="admin-phone"]').setValue('13900139000')
    await wrapper.get('[data-testid="tenant-expiry"]').setValue('2026-10-01T08:00')
    await wrapper.get('.create-form').trigger('submit')
    await vi.waitFor(() => expect(apiMocks.createTenant).toHaveBeenCalledOnce())
    expect(apiMocks.createTenant).toHaveBeenCalledWith(
      {
        name: '租户乙',
        admin_phone: '13900139000',
        expires_at: '2026-10-01T00:00:00.000Z',
      },
      'platform-csrf',
    )

    await wrapper.get('[data-testid="expiry-8"]').setValue('2026-11-01T08:00')
    await wrapper.get('[data-testid="save-expiry-8"]').trigger('click')
    expect(apiMocks.patchTenant).toHaveBeenCalledWith(
      8,
      { expires_at: '2026-11-01T00:00:00.000Z' },
      'platform-csrf',
    )

    await wrapper.get('[data-testid="extend-8"]').trigger('click')
    expect(apiMocks.patchTenant).toHaveBeenCalledWith(
      8,
      { extend_days: 30 },
      'platform-csrf',
    )

    await wrapper.get('[data-testid="status-8"]').trigger('click')
    expect(apiMocks.patchTenant).toHaveBeenCalledWith(
      8,
      { status: 'suspended' },
      'platform-csrf',
    )

    await wrapper.get('[data-testid="status-8"]').trigger('click')
    expect(apiMocks.patchTenant).toHaveBeenLastCalledWith(
      8,
      { status: 'active' },
      'platform-csrf',
    )

    await wrapper.get('[data-testid="retry-8"]').trigger('click')
    expect(apiMocks.retryTenant).toHaveBeenCalledWith(8, 'platform-csrf')
  })
})
