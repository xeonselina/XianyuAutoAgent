## 1. 背景 (Background)

• **平台现状：** 当前 GPU 平台主要通过 TKE Serverless (EKS) 模式管理资源，实现了资源的跨集群调度和闲置资源复用。

• **新需求引入：** 随着大模型训练等高性能场景的增加，业务需要使用多机多卡推理，依赖 RDMA 网络。业务需要使用 **TKE 物理机（Node 模式）**。这类资源具有物理独占、

• **混合架构挑战：** 平台将同时存在 EKS（弹性池）和 TKE（物理独占）两种资源形态，需要一套统一的管理机制来兼容两者的生命周期差异。

## 2. 问题 (Problem)

• **用户体验割裂：** 如果让用户在申请时区分“EKS 配额”和“TKE 配额”，会增加理解成本，且配额碎片化严重[Conversation]。

• **物理资源弹性难：** TKE 物理机是整机交付，无法像 EKS 那样在业务缩容后直接退还给公有云大池子进行售卖，容易造成独占资源的闲置浪费。

• **保障与复用的冲突：** 业务既需要 100% 的资源保障（如“资源锁定”能力），又希望通过 CronHPA 释放闲置资源以降低成本，物理机模式下如何平衡这两点是核心痛点[Conversation]。

## 3. 目标 (Objective)

• **统一配额视图：** 对用户暴露统一的配额概念（地域/机型/卡数），屏蔽底层的 EKS 与 TKE 差异 [Conversation]。

• **精准资源投放：** 后端根据业务特征（如多机多卡）自动匹配资源形态（EKS vs TKE），实现“前端一本账，后端两条路” [Conversation]。

• **极致资源利用：** 针对 TKE 物理机实现 **“原地潮汐复用”**，在节点不退场的情况下，利用低优先级任务填充波谷时段 [Conversation]。

• **资源确定性保障：** 无论哪种形态，必须确保业务在需要时能瞬间拿回资源（通过预切片或抢占机制）

## 4. 用户故事 (User Stories)

• **场景一：申请高性能训练资源（TKE 路径）**

  ◦ **用户：** 申请一批 GPU 配额，并勾选了“多机多卡”或“RDMA”选项。

  ◦ **平台：** 后端识别该需求必须由物理机满足，在“资源交付策略表”中标记为 **TKE**。运管将物理机加入用户集群，并打上专用污点（Taint）。

  ◦ **结果：** 用户看到的只是“配额已生效”，创建任务时 Pod 自动调度到专属物理节点上 [Conversation]。

• **场景二：申请通用推理资源（EKS 路径）**

  ◦ **用户：** 申请普通推理配额。

  ◦ **平台：** 后端识别为通用需求，标记为 **EKS**。

  ◦ **结果：** 配额审批通过即生效，用户 Pod 运行在 Serverless 虚拟节点上，资源随用随取 [Conversation]。

• **场景三：物理机资源的潮汐复用（原地出让）**

  ◦ **用户：** 针对 TKE 资源配置了 CronHPA，夜间将副本数从 100 缩容至 20。

  ◦ **平台：** 物理节点（Node）保持在线，但在 Kubernetes 层面出现空闲。平台调度 **低优先级（Low Priority）** 的离线任务或 Spot 实例到这些节点上。

  ◦ **结果：** 节点没闲着（资源利用率高），一旦用户业务需要扩容，低优任务被驱逐，资源毫秒级归还 [Conversation]。

## 5. 功能需求 (Functional Requirements)

5.1 资源申请与识别 (Resource Request & Identification)

• **统一配额接口：** CRP 申请单仅保留地域、卡型、CPU/内存规格、数量，去除“资源形态”选择[Conversation]。

```mermaid
graph TD
    User[用户(CRP)] -->|提交申请: 地域/卡型/数量| Quota[统一配额接口]
    
    subgraph 核心分流逻辑
    Quota --> Check{特征识别}
    Check -->|普通推理| StrategyA[标记策略: EKS Serverless]
    Check -->|多机多卡/RDMA/裸金属| StrategyB[标记策略: TKE Node物理机]
    end
    
    subgraph 资源交付层
    StrategyA -->|API调用| EKS_Pool[EKS 弹性资源池]
    EKS_Pool -->|虚拟节点| VK[Virtual Kubelet]
    
    StrategyB -->|物理上架| Phy_Node[TKE 物理节点]
    Phy_Node -->|纳管+打标| Taint[注入 Taint & Label\n(专属独占)]
    end
    
    VK -.->|状态同步| Status[配额生效]
    Taint -.->|Node Ready| Status
```

• **交付策略引擎：** 后端新增逻辑，根据用户勾选的特性（RDMA、裸金属、多机互联）写入“资源交付策略表”，区分 `Strategy=EKS` 或 `Strategy=TKE_Node` [Conversation]。

5.2 资源投放与上线 (Delivery & Onboarding)

• **TKE 专属纳管：** 支持物理机自动加入指定 TKE 集群，并自动注入 **Taint（污点）** 和 **Label（标签）** 以实现资源物理隔离（预切片） [Conversation]。

• **配额生效触发器：**

  ◦ EKS：逻辑扣减库存即生效。

  ◦ TKE：监听物理 Node 状态，当 Node 变为 `Ready` 且标签同步完成后，配额状态流转为“生效” [Conversation]。

5.3 弹性与潮汐 (Elasticity & Tidal Reuse)

• **CronHPA/HPA 支持：** 支持用户配置定时或指标驱动的扩缩容。

• **差异化出让机制：**

  ◦ **EKS 模式：** 缩容销毁 Pod，资源退回 Serverless 池。

  ◦ **TKE 模式：** 缩容销毁 Pod，资源 **滞留** 在 Node 上。系统需具备 **“低优先级注入能力”**，将潮汐任务调度到用户专属 Node 上 [Conversation]。

5.4 资源保障 (Resource Assurance)

• **资源锁定（Resource Locking）：** 提供应用级开关。开启后，即使 HPA 缩容，TKE 物理机的 Node 也不允许被其他**高优**业务抢占（仅允许低优潮汐任务复用）。

• **抢占式回收（Preemption）：** 对于 TKE 模式，当专属业务扩容时，调度器必须强制驱逐 Node 上的潮汐任务/Spot 任务，保障专属业务 Pod 优先调度 [Conversation]。