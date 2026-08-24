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
import {
  installAuthGuards,
  navigateAfterTenantLogin,
} from '@/router'
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

const apiRejection = (message: string, status: number) => Object.assign(
  new Error(message),
  {
    isAxiosError: true,
    response: {
      status,
      data: { success: false, message, code: 'INVALID_REQUEST' },
    },
  },
)

const deferred = <T>() => {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, reject, resolve }
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

  it('returns an unauthenticated mobile visit through desktop login to the mobile SPA', async () => {
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

    const desktopLoginUrl = new URL(assign.mock.calls[0][0], 'https://example.test')
    const routerReplace = vi.fn()
    const browserReplace = vi.fn()
    await navigateAfterTenantLogin(
      desktopLoginUrl.searchParams.get('next'),
      routerReplace,
      browserReplace,
    )

    expect(browserReplace).toHaveBeenCalledWith(
      '/mobile/edit-rental/9?source=scan',
    )
    expect(routerReplace).not.toHaveBeenCalled()
  })

  it.each(['expired', 'suspended'])(
    'sends an authenticated %s mobile tenant to the desktop restricted page',
    async (accessStatus) => {
      const assign = vi.fn()
      const guard = createMobileAuthGuard(
        vi.fn().mockResolvedValue(true),
        assign,
        () => accessStatus,
      )

      const result = await guard({ fullPath: '/gantt' })

      expect(result).toBe(false)
      expect(assign).toHaveBeenCalledWith(
        `/access-restricted?reason=${accessStatus}`,
      )
    },
  )

  it('allows an authenticated active mobile tenant to continue', async () => {
    const assign = vi.fn()
    const guard = createMobileAuthGuard(
      vi.fn().mockResolvedValue(true),
      assign,
      () => 'active',
    )

    const result = await guard({ fullPath: '/gantt' })

    expect(result).toBe(true)
    expect(assign).not.toHaveBeenCalled()
  })

  it.each([
    { label: 'provisioning', accessStatus: 'provisioning' },
    { label: 'failed', accessStatus: 'failed' },
    { label: 'missing', accessStatus: undefined },
    { label: 'future unknown', accessStatus: 'future-server-state' },
  ])(
    'fails closed for an authenticated mobile tenant with $label status',
    async ({ accessStatus }) => {
      const assign = vi.fn()
      const guard = createMobileAuthGuard(
        vi.fn().mockResolvedValue(true),
        assign,
        () => accessStatus,
      )

      const result = await guard({ fullPath: '/gantt' })

      expect(result).toBe(false)
      expect(assign).toHaveBeenCalledWith(
        '/access-restricted?reason=restricted',
      )
    },
  )

  it.each([
    'https://attacker.example/mobile/gantt',
    '//attacker.example/mobile/gantt',
    '/platform/tenants',
    '/PLATFORM/tenants',
    '/mobile/%2e%2e/platform/tenants',
    '/mobile/%2E%2E/%50LATFORM/tenants',
    '/mobile%2F..%2Fplatform/tenants',
    '/mobile/%252e%252e/%252e%252e//attacker.example/x',
    '/mobile/%252e%252e/%252e%252e//platform/tenants',
    '/mobile/%25252e%25252e/%25252e%25252e//platform/tenants',
    '/mobile/%252e%252e/%252e%252e/%252f%252fplatform/tenants',
    '/\\attacker.example/mobile/gantt',
  ])('rejects an unsafe tenant login next value: %s', async (next) => {
    const routerReplace = vi.fn()
    const browserReplace = vi.fn()

    await navigateAfterTenantLogin(next, routerReplace, browserReplace)

    expect(routerReplace).toHaveBeenCalledWith('/')
    expect(browserReplace).not.toHaveBeenCalled()
  })

  it('keeps a valid encoded desktop tenant path inside the desktop router', async () => {
    const routerReplace = vi.fn()
    const browserReplace = vi.fn()

    await navigateAfterTenantLogin(
      '/search?keyword=%E6%B5%8B%E8%AF%95',
      routerReplace,
      browserReplace,
    )

    expect(routerReplace).toHaveBeenCalledWith(
      '/search?keyword=%E6%B5%8B%E8%AF%95',
    )
    expect(browserReplace).not.toHaveBeenCalled()
  })
})

describe('tenant auth store and login form', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.resetAllMocks()
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
    vi.resetAllMocks()
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
    await vi.waitFor(() => {
      expect(apiMocks.listTenants).toHaveBeenCalledOnce()
      expect(
        (wrapper.get('[data-testid="new-tenant"]').element as HTMLButtonElement).disabled,
      ).toBe(false)
      expect(wrapper.find('[data-testid="status-8"]').exists()).toBe(true)
    })
    await nextTick()

    await wrapper.get('[data-testid="new-tenant"]').trigger('click')
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="tenant-name"]').exists()).toBe(true)
    })
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

  it('labels an ordinary tenant list load failure clearly', async () => {
    apiMocks.listTenants.mockRejectedValue(
      apiRejection('控制库暂时不可用', 503),
    )
    const pinia = createPinia()
    setActivePinia(pinia)
    useAuthStore().applyPlatformSession(platformData)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', component: PlatformTenantsView }],
    })
    await router.push('/')
    await router.isReady()
    const wrapper = mount(PlatformTenantsView, {
      global: { plugins: [pinia, router] },
    })

    await vi.waitFor(() => {
      expect(wrapper.get('[role="alert"]').text()).toBe(
        '列表加载失败：控制库暂时不可用',
      )
    })
  })

  it('preserves a rejected create error after refreshing and clears it on success', async () => {
    const tenant = {
      id: 8,
      name: '租户甲',
      status: 'active',
      expires_at: '2026-09-30T00:00:00Z',
      db_name: 'inventory_tenant_00000008',
      provisioning_status: 'active',
      provisioning_error: null,
      admin_phone: '+8613800138000',
    }
    apiMocks.listTenants.mockResolvedValue([tenant])
    apiMocks.createTenant
      .mockRejectedValueOnce(apiRejection('该手机号已属于其他租户', 409))
      .mockResolvedValueOnce({ ...tenant, id: 9, name: '租户乙' })
    const pinia = createPinia()
    setActivePinia(pinia)
    useAuthStore().applyPlatformSession(platformData)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', component: PlatformTenantsView }],
    })
    await router.push('/')
    await router.isReady()
    const wrapper = mount(PlatformTenantsView, {
      global: { plugins: [pinia, router] },
    })
    await vi.waitFor(() => {
      expect(apiMocks.listTenants).toHaveBeenCalledOnce()
      expect(
        (wrapper.get('[data-testid="new-tenant"]').element as HTMLButtonElement).disabled,
      ).toBe(false)
      expect(wrapper.find('[data-testid="status-8"]').exists()).toBe(true)
    })

    await wrapper.get('[data-testid="new-tenant"]').trigger('click')
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="tenant-name"]').exists()).toBe(true)
    })
    await wrapper.get('[data-testid="tenant-name"]').setValue('租户乙')
    await wrapper.get('[data-testid="admin-phone"]').setValue('13900139000')
    await wrapper.get('[data-testid="tenant-expiry"]').setValue('2026-10-01T08:00')
    await wrapper.get('.create-form').trigger('submit')

    await vi.waitFor(() => {
      expect(apiMocks.listTenants).toHaveBeenCalledTimes(2)
      expect(wrapper.get('[role="alert"]').text()).toBe('该手机号已属于其他租户')
    })

    await wrapper.get('.create-form').trigger('submit')
    await vi.waitFor(() => expect(apiMocks.createTenant).toHaveBeenCalledTimes(2))
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('preserves a rejected retry error after refreshing and clears it on success', async () => {
    const failedTenant = {
      id: 8,
      name: '租户甲',
      status: 'active',
      expires_at: '2026-09-30T00:00:00Z',
      db_name: 'inventory_tenant_00000008',
      provisioning_status: 'failed',
      provisioning_error: 'migration failed',
      admin_phone: '+8613800138000',
    }
    apiMocks.listTenants.mockResolvedValue([failedTenant])
    apiMocks.retryTenant
      .mockRejectedValueOnce(apiRejection('租户当前状态不能重试', 400))
      .mockResolvedValueOnce({
        ...failedTenant,
        provisioning_status: 'active',
        provisioning_error: null,
      })
    const pinia = createPinia()
    setActivePinia(pinia)
    useAuthStore().applyPlatformSession(platformData)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', component: PlatformTenantsView }],
    })
    await router.push('/')
    await router.isReady()
    const wrapper = mount(PlatformTenantsView, {
      global: { plugins: [pinia, router] },
    })
    await vi.waitFor(() => {
      expect(apiMocks.listTenants).toHaveBeenCalledOnce()
      expect(wrapper.find('[data-testid="retry-8"]').exists()).toBe(true)
    })

    await wrapper.get('[data-testid="retry-8"]').trigger('click')
    await vi.waitFor(() => {
      expect(apiMocks.listTenants).toHaveBeenCalledTimes(2)
      expect(wrapper.get('[role="alert"]').text()).toBe('租户当前状态不能重试')
    })

    await wrapper.get('[data-testid="retry-8"]').trigger('click')
    await vi.waitFor(() => expect(apiMocks.retryTenant).toHaveBeenCalledTimes(2))
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('shows both the create failure and a failed follow-up list refresh', async () => {
    const tenant = {
      id: 8,
      name: '租户甲',
      status: 'active',
      expires_at: '2026-09-30T00:00:00Z',
      db_name: 'inventory_tenant_00000008',
      provisioning_status: 'active',
      provisioning_error: null,
      admin_phone: '+8613800138000',
    }
    apiMocks.listTenants
      .mockResolvedValueOnce([tenant])
      .mockRejectedValueOnce(apiRejection('控制库暂时不可用', 503))
    apiMocks.createTenant.mockRejectedValue(
      apiRejection('该手机号已属于其他租户', 409),
    )
    const pinia = createPinia()
    setActivePinia(pinia)
    useAuthStore().applyPlatformSession(platformData)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', component: PlatformTenantsView }],
    })
    await router.push('/')
    await router.isReady()
    const wrapper = mount(PlatformTenantsView, {
      global: { plugins: [pinia, router] },
    })
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="status-8"]').exists()).toBe(true)
    })

    await wrapper.get('[data-testid="new-tenant"]').trigger('click')
    await wrapper.get('[data-testid="tenant-name"]').setValue('租户乙')
    await wrapper.get('[data-testid="admin-phone"]').setValue('13900139000')
    await wrapper.get('[data-testid="tenant-expiry"]').setValue('2026-10-01T08:00')
    await wrapper.get('.create-form').trigger('submit')

    await vi.waitFor(() => {
      expect(apiMocks.listTenants).toHaveBeenCalledTimes(2)
      expect(wrapper.get('[role="alert"]').text()).toContain('该手机号已属于其他租户')
      expect(wrapper.get('[role="alert"]').text()).toContain(
        '列表刷新失败，数据可能已过期：控制库暂时不可用',
      )
    })
  })

  it('shows both the retry failure and a failed follow-up list refresh', async () => {
    const failedTenant = {
      id: 8,
      name: '租户甲',
      status: 'active',
      expires_at: '2026-09-30T00:00:00Z',
      db_name: 'inventory_tenant_00000008',
      provisioning_status: 'failed',
      provisioning_error: 'migration failed',
      admin_phone: '+8613800138000',
    }
    apiMocks.listTenants
      .mockResolvedValueOnce([failedTenant])
      .mockRejectedValueOnce(apiRejection('控制库暂时不可用', 503))
    apiMocks.retryTenant.mockRejectedValue(
      apiRejection('租户当前状态不能重试', 400),
    )
    const pinia = createPinia()
    setActivePinia(pinia)
    useAuthStore().applyPlatformSession(platformData)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', component: PlatformTenantsView }],
    })
    await router.push('/')
    await router.isReady()
    const wrapper = mount(PlatformTenantsView, {
      global: { plugins: [pinia, router] },
    })
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="retry-8"]').exists()).toBe(true)
    })

    await wrapper.get('[data-testid="retry-8"]').trigger('click')

    await vi.waitFor(() => {
      expect(apiMocks.listTenants).toHaveBeenCalledTimes(2)
      expect(wrapper.get('[role="alert"]').text()).toContain(
        '租户当前状态不能重试',
      )
      expect(wrapper.get('[role="alert"]').text()).toContain(
        '列表刷新失败，数据可能已过期：控制库暂时不可用',
      )
    })
  })

  it('locks duplicate create submissions and disables every tenant mutation control', async () => {
    const failedTenant = {
      id: 8,
      name: '租户甲',
      status: 'active',
      expires_at: '2026-09-30T00:00:00Z',
      db_name: 'inventory_tenant_00000008',
      provisioning_status: 'failed',
      provisioning_error: 'migration failed',
      admin_phone: '+8613800138000',
    }
    const pendingCreate = deferred<typeof failedTenant>()
    apiMocks.listTenants.mockResolvedValue([failedTenant])
    apiMocks.createTenant.mockReturnValue(pendingCreate.promise)
    const pinia = createPinia()
    setActivePinia(pinia)
    useAuthStore().applyPlatformSession(platformData)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', component: PlatformTenantsView }],
    })
    await router.push('/')
    await router.isReady()
    const wrapper = mount(PlatformTenantsView, {
      global: { plugins: [pinia, router] },
    })
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="retry-8"]').exists()).toBe(true)
    })

    await wrapper.get('[data-testid="new-tenant"]').trigger('click')
    await wrapper.get('[data-testid="tenant-name"]').setValue('租户乙')
    await wrapper.get('[data-testid="admin-phone"]').setValue('13900139000')
    await wrapper.get('[data-testid="tenant-expiry"]').setValue('2026-10-01T08:00')
    await wrapper.get('.create-form').trigger('submit')
    await vi.waitFor(() => expect(apiMocks.createTenant).toHaveBeenCalledOnce())

    await vi.waitFor(() => {
      expect(
        (wrapper.get('[data-testid="create-tenant"]').element as HTMLButtonElement).disabled,
      ).toBe(true)
      expect(
        (wrapper.get('[data-testid="status-8"]').element as HTMLButtonElement).disabled,
      ).toBe(true)
      expect(
        (wrapper.get('[data-testid="retry-8"]').element as HTMLButtonElement).disabled,
      ).toBe(true)
    })
    await wrapper.get('.create-form').trigger('submit')
    expect(apiMocks.createTenant).toHaveBeenCalledOnce()

    pendingCreate.resolve({ ...failedTenant, id: 9, provisioning_status: 'active' })
    await vi.waitFor(() => {
      expect(wrapper.find('.create-form').exists()).toBe(false)
    })
  })

  it('serializes an older create failure before a later success without leaving stale error', async () => {
    const tenant = {
      id: 8,
      name: '租户甲',
      status: 'active',
      expires_at: '2026-09-30T00:00:00Z',
      db_name: 'inventory_tenant_00000008',
      provisioning_status: 'active',
      provisioning_error: null,
      admin_phone: '+8613800138000',
    }
    const earlierFailure = deferred<typeof tenant>()
    const laterSuccess = deferred<typeof tenant>()
    apiMocks.listTenants.mockResolvedValue([tenant])
    apiMocks.createTenant
      .mockReturnValueOnce(earlierFailure.promise)
      .mockReturnValueOnce(laterSuccess.promise)
    const pinia = createPinia()
    setActivePinia(pinia)
    useAuthStore().applyPlatformSession(platformData)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', component: PlatformTenantsView }],
    })
    await router.push('/')
    await router.isReady()
    const wrapper = mount(PlatformTenantsView, {
      global: { plugins: [pinia, router] },
    })
    await vi.waitFor(() => {
      expect(apiMocks.listTenants).toHaveBeenCalledOnce()
      expect(
        (wrapper.get('[data-testid="new-tenant"]').element as HTMLButtonElement).disabled,
      ).toBe(false)
      expect(wrapper.find('[data-testid="status-8"]').exists()).toBe(true)
    })

    await wrapper.get('[data-testid="new-tenant"]').trigger('click')
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="tenant-name"]').exists()).toBe(true)
    })
    await wrapper.get('[data-testid="tenant-name"]').setValue('租户乙')
    await wrapper.get('[data-testid="admin-phone"]').setValue('13900139000')
    await wrapper.get('[data-testid="tenant-expiry"]').setValue('2026-10-01T08:00')
    await wrapper.get('.create-form').trigger('submit')
    await wrapper.get('.create-form').trigger('submit')
    expect(apiMocks.createTenant).toHaveBeenCalledOnce()

    earlierFailure.reject(apiRejection('较早的创建失败', 409))
    await vi.waitFor(() => {
      expect(wrapper.get('[role="alert"]').text()).toBe('较早的创建失败')
    })

    await wrapper.get('.create-form').trigger('submit')
    await vi.waitFor(() => expect(apiMocks.createTenant).toHaveBeenCalledTimes(2))
    laterSuccess.resolve({ ...tenant, id: 9, name: '租户乙' })
    await vi.waitFor(() => {
      expect(wrapper.find('[role="alert"]').exists()).toBe(false)
      expect(wrapper.find('.create-form').exists()).toBe(false)
    })
  })
})
