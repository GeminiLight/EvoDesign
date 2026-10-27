// TODO(PRD-005): Replace with real backend API
// ────────────────────────────────────────────
// Gallery Mock Data — types + 12 works, 6 DNA, ranking lists
// ────────────────────────────────────────────

export type IndustryTag =
  | 'fintech'
  | 'healthcare'
  | 'ecommerce'
  | 'devops'
  | 'education'
  | 'gaming'
  | 'saas'
  | 'iot';

export type ComplexityTag = 'simple' | 'medium' | 'complex';

export type ThumbnailSize = 'sm' | 'md' | 'lg';

export interface ThumbnailNode {
  x: number;
  y: number;
  w: number;
  h: number;
  rx: number;
  color: string;
  /** short text label rendered inside the node */
  label?: string;
  /** stagger index for timelapse animation */
  delay: number;
}

export interface ThumbnailEdge {
  label?: string;
  labelX?: number;
  labelY?: number;
  d: string;
  color: string;
  delay: number;
}

export interface GalleryWork {
  id: string;
  title: string;
  titleZh: string;
  author: string;
  avatarColor: string;
  diagramType: string;
  industry: IndustryTag;
  complexity: ComplexityTag;
  cloneCount: number;
  viewCount: number;
  createdAt: string;
  agentVersion: string;
  thumbnailSize: ThumbnailSize;
  thumbnail: {
    viewBox: string;
    nodes: ThumbnailNode[];
    edges: ThumbnailEdge[];
  };
  description: string;
  descriptionZh: string;
}

export interface DnaVariant {
  label: string;
  labelZh: string;
  previewColors: [string, string, string];
}

export interface GalleryDna {
  id: string;
  name: string;
  nameZh: string;
  author: string;
  avatarColor: string;
  injectCount: number;
  category: 'structure' | 'style' | 'layout';
  variants: DnaVariant[];
  description: string;
  descriptionZh: string;
  tags: string[];
  tagsZh: string[];
}

// ─── Brand palette helpers ────────────────
const B5 = '#318dff';
const B4 = '#52aeff';
const B6 = '#1e6ef5';
const SLATE3 = '#cbd5e1';
const EMERALD = '#10b981';
const AMBER = '#f59e0b';
const ROSE = '#f43f5e';
const VIOLET = '#8b5cf6';

// ─── 12 Mock Works ────────────────────────
export const GALLERY_WORKS: GalleryWork[] = [
  {
    id: 'w1',
    title: 'Payment Gateway Architecture',
    titleZh: '支付网关架构图',
    author: 'Alex Chen',
    avatarColor: 'bg-blue-500',
    diagramType: 'architecture',
    industry: 'fintech',
    complexity: 'complex',
    cloneCount: 342,
    viewCount: 1820,
    createdAt: '2026-02-20',
    agentVersion: 'v2.3',
    thumbnailSize: 'lg',
    thumbnail: {
      viewBox: '0 0 280 156',
      nodes: [
        { x: 20, y: 15, w: 72, h: 21, rx: 8, color: B5, label: 'API Gateway', delay: 0 },
        { x: 110, y: 15, w: 72, h: 21, rx: 8, color: B6, label: 'Auth Svc', delay: 1 },
        { x: 200, y: 15, w: 60, h: 21, rx: 8, color: EMERALD, label: 'Order Svc', delay: 2 },
        { x: 60, y: 60, w: 80, h: 21, rx: 8, color: B4, label: 'Message Queue', delay: 3 },
        { x: 160, y: 60, w: 80, h: 21, rx: 8, color: VIOLET, label: 'Payment Svc', delay: 4 },
        { x: 100, y: 112, w: 80, h: 21, rx: 8, color: AMBER, label: 'Settlement', delay: 5 },
      ],
      edges: [
        { d: 'M92 26 L110 26', color: SLATE3, delay: 0 },
        { d: 'M182 26 L200 26', color: SLATE3, delay: 1 },
        { d: 'M56 36 L100 60', color: SLATE3, delay: 2 },
        { d: 'M146 36 L200 60', color: SLATE3, delay: 3 },
        { d: 'M100 81 V99 H140 V112', color: SLATE3, delay: 4 },
      ],
    },
    description: 'A multi-layer payment gateway with fraud detection, tokenization, and settlement routing.',
    descriptionZh: '多层支付网关，包含欺诈检测、令牌化和清算路由。',
  },
  {
    id: 'w2',
    title: 'Patient Record Flow',
    titleZh: '患者病历流程',
    author: 'Sarah Liu',
    avatarColor: 'bg-emerald-500',
    diagramType: 'flowchart',
    industry: 'healthcare',
    complexity: 'medium',
    cloneCount: 189,
    viewCount: 1240,
    createdAt: '2026-02-18',
    agentVersion: 'v2.1',
    thumbnailSize: 'md',
    thumbnail: {
      viewBox: '0 0 280 160',
      nodes: [
        { x: 30, y: 20, w: 60, h: 24, rx: 12, color: EMERALD, label: 'Admission', delay: 0 },
        { x: 120, y: 20, w: 60, h: 24, rx: 6, color: B5, label: 'Diagnosis', delay: 1 },
        { x: 120, y: 70, w: 60, h: 24, rx: 6, color: B4, label: 'Treatment', delay: 2 },
        { x: 30, y: 120, w: 60, h: 24, rx: 6, color: AMBER, label: 'Discharge', delay: 3 },
        { x: 200, y: 70, w: 60, h: 24, rx: 6, color: VIOLET, label: 'EHR Sync', delay: 4 },
      ],
      edges: [
        { d: 'M90 32 L120 32', color: SLATE3, delay: 0 },
        { d: 'M150 44 L150 70', color: SLATE3, delay: 1 },
        { d: 'M120 82 L90 120', color: SLATE3, delay: 2 },
        { d: 'M180 82 L200 82', color: SLATE3, delay: 3 },
      ],
    },
    description: 'End-to-end patient record lifecycle from admission to discharge with EHR integration.',
    descriptionZh: '从入院到出院的端到端患者病历生命周期，集成电子健康记录。',
  },
  {
    id: 'w3',
    title: 'E-Commerce Order Pipeline',
    titleZh: '电商订单流水线',
    author: 'Marcus Kim',
    avatarColor: 'bg-amber-500',
    diagramType: 'sequence',
    industry: 'ecommerce',
    complexity: 'complex',
    cloneCount: 278,
    viewCount: 1560,
    createdAt: '2026-02-15',
    agentVersion: 'v2.3',
    thumbnailSize: 'lg',
    thumbnail: {
      viewBox: '0 0 280 156',
      nodes: [
        { x: 20, y: 8, w: 50, h: 15, rx: 4, color: B5, label: 'Browser', delay: 0 },
        { x: 90, y: 8, w: 50, h: 15, rx: 4, color: B6, label: 'Cart Svc', delay: 1 },
        { x: 160, y: 8, w: 50, h: 15, rx: 4, color: EMERALD, label: 'Payment', delay: 2 },
        { x: 230, y: 8, w: 40, h: 15, rx: 4, color: AMBER, label: 'Shipping', delay: 3 },
      ],
      edges: [
        { d: 'M45 22 L45 142', color: SLATE3, delay: 0 },
        { d: 'M115 22 L115 142', color: SLATE3, delay: 0 },
        { d: 'M185 22 L185 142', color: SLATE3, delay: 0 },
        { d: 'M250 22 L250 142', color: SLATE3, delay: 0 },
        { d: 'M45 38 L115 38', label: 'Order', labelX: 80, labelY: 34, color: B5, delay: 1 },
        { d: 'M115 52 L185 52', label: 'Charge', labelX: 150, labelY: 50, color: EMERALD, delay: 2 },
        { d: 'M185 68 L250 68', label: 'Ship', labelX: 217, labelY: 64, color: AMBER, delay: 3 },
        { d: 'M250 82 L185 82', label: 'Confirm', labelX: 217, labelY: 80, color: AMBER, delay: 4 },
        { d: 'M185 98 L115 98', label: 'Paid', labelX: 150, labelY: 94, color: EMERALD, delay: 5 },
        { d: 'M115 112 L45 112', label: 'Receipt', labelX: 80, labelY: 110, color: B5, delay: 6 },
      ],
    },
    description: 'Full sequence diagram for e-commerce order processing including inventory, payment, and shipping.',
    descriptionZh: '电商订单处理完整时序图，涵盖库存、支付和物流环节。',
  },
  {
    id: 'w4',
    title: 'CI/CD Pipeline Overview',
    titleZh: 'CI/CD 流水线概览',
    author: 'Dev Team',
    avatarColor: 'bg-violet-500',
    diagramType: 'flowchart',
    industry: 'devops',
    complexity: 'medium',
    cloneCount: 456,
    viewCount: 2340,
    createdAt: '2026-02-22',
    agentVersion: 'v2.2',
    thumbnailSize: 'sm',
    thumbnail: {
      viewBox: '0 0 280 120',
      nodes: [
        { x: 10, y: 46, w: 50, h: 24, rx: 6, color: B5, label: 'Commit', delay: 0 },
        { x: 78, y: 46, w: 50, h: 24, rx: 6, color: B4, label: 'Test', delay: 1 },
        { x: 146, y: 46, w: 50, h: 24, rx: 6, color: EMERALD, label: 'Build', delay: 2 },
        { x: 214, y: 46, w: 56, h: 24, rx: 6, color: AMBER, label: 'Deploy', delay: 3 },
      ],
      edges: [
        { d: 'M60 58 L78 58', color: SLATE3, delay: 0 },
        { d: 'M128 58 L146 58', color: SLATE3, delay: 1 },
        { d: 'M196 58 L214 58', color: SLATE3, delay: 2 },
      ],
    },
    description: 'Streamlined CI/CD flow from code commit to production deployment with quality gates.',
    descriptionZh: '从代码提交到生产部署的精简 CI/CD 流程，含质量门禁。',
  },
  {
    id: 'w5',
    title: 'LMS Module Map',
    titleZh: '学习管理系统模块图',
    author: 'Edu Labs',
    avatarColor: 'bg-pink-500',
    diagramType: 'mindmap',
    industry: 'education',
    complexity: 'simple',
    cloneCount: 124,
    viewCount: 890,
    createdAt: '2026-02-12',
    agentVersion: 'v2.0',
    thumbnailSize: 'md',
    thumbnail: {
      viewBox: '0 0 280 160',
      nodes: [
        { x: 110, y: 60, w: 60, h: 28, rx: 14, color: B5, label: 'Learning', delay: 0 },
        { x: 20, y: 20, w: 56, h: 22, rx: 6, color: EMERALD, label: 'Courses', delay: 1 },
        { x: 200, y: 20, w: 56, h: 22, rx: 6, color: AMBER, label: 'Quizzes', delay: 2 },
        { x: 20, y: 110, w: 56, h: 22, rx: 6, color: VIOLET, label: 'Progress', delay: 3 },
        { x: 200, y: 110, w: 56, h: 22, rx: 6, color: ROSE, label: 'Certificates', delay: 4 },
      ],
      edges: [
        { d: 'M110 74 L76 31', color: SLATE3, delay: 0 },
        { d: 'M170 74 L200 31', color: SLATE3, delay: 1 },
        { d: 'M110 88 L76 121', color: SLATE3, delay: 2 },
        { d: 'M170 88 L200 121', color: SLATE3, delay: 3 },
      ],
    },
    description: 'A learning management system mind map covering courses, quizzes, progress tracking, and certifications.',
    descriptionZh: '学习管理系统思维导图，涵盖课程、测验、进度追踪和认证模块。',
  },
  {
    id: 'w6',
    title: 'Game Server Topology',
    titleZh: '游戏服务器拓扑',
    author: 'Pixel Studio',
    avatarColor: 'bg-red-500',
    diagramType: 'network',
    industry: 'gaming',
    complexity: 'complex',
    cloneCount: 201,
    viewCount: 1100,
    createdAt: '2026-02-24',
    agentVersion: 'v2.3',
    thumbnailSize: 'lg',
    thumbnail: {
      viewBox: '0 0 280 156',
      nodes: [
        { x: 110, y: 8, w: 60, h: 18, rx: 12, color: ROSE, label: 'Gateway', delay: 0 },
        { x: 20, y: 60, w: 56, h: 18, rx: 6, color: B5, label: 'Lobby', delay: 1 },
        { x: 110, y: 60, w: 56, h: 18, rx: 6, color: EMERALD, label: 'Matching', delay: 2 },
        { x: 200, y: 60, w: 56, h: 18, rx: 6, color: AMBER, label: 'Relay', delay: 3 },
        { x: 60, y: 116, w: 56, h: 18, rx: 6, color: VIOLET, label: 'Players', delay: 4 },
        { x: 165, y: 116, w: 56, h: 18, rx: 6, color: B4, label: 'Game state', delay: 5 },
      ],
      edges: [
        { d: 'M140 26 L48 60', color: SLATE3, delay: 0 },
        { d: 'M140 26 L138 60', color: SLATE3, delay: 1 },
        { d: 'M140 26 L228 60', color: SLATE3, delay: 2 },
        { d: 'M48 78 L88 116', color: SLATE3, delay: 3 },
        { d: 'M228 78 L193 116', color: SLATE3, delay: 4 },
      ],
    },
    description: 'Distributed game server network with lobby, match-making, and regional relay nodes.',
    descriptionZh: '分布式游戏服务器网络，包含大厅、匹配和区域中继节点。',
  },
  {
    id: 'w7',
    title: 'SaaS Multi-Tenant DB Schema',
    titleZh: 'SaaS 多租户数据库架构',
    author: 'CloudArch',
    avatarColor: 'bg-indigo-500',
    diagramType: 'er',
    industry: 'saas',
    complexity: 'complex',
    cloneCount: 315,
    viewCount: 1780,
    createdAt: '2026-02-25',
    agentVersion: 'v2.3',
    thumbnailSize: 'md',
    thumbnail: {
      viewBox: '0 0 280 160',
      nodes: [
        { x: 20, y: 20, w: 72, h: 24, rx: 4, color: B6, label: 'Tenants', delay: 0 },
        { x: 20, y: 70, w: 72, h: 24, rx: 4, color: B5, label: 'Users', delay: 1 },
        { x: 20, y: 120, w: 72, h: 24, rx: 4, color: B4, label: 'Roles', delay: 2 },
        { x: 170, y: 20, w: 72, h: 24, rx: 4, color: EMERALD, label: 'Projects', delay: 3 },
        { x: 170, y: 70, w: 72, h: 24, rx: 4, color: AMBER, label: 'Resources', delay: 4 },
        { x: 170, y: 120, w: 72, h: 24, rx: 4, color: VIOLET, label: 'Policies', delay: 5 },
      ],
      edges: [
        { d: 'M92 32 L170 32', color: SLATE3, delay: 0 },
        { d: 'M92 82 L170 82', color: SLATE3, delay: 1 },
        { d: 'M92 132 L170 132', color: SLATE3, delay: 2 },
        { d: 'M56 44 L56 70', color: SLATE3, delay: 3 },
        { d: 'M206 44 L206 70', color: SLATE3, delay: 4 },
      ],
    },
    description: 'ER diagram for SaaS multi-tenant architecture with tenant isolation and shared resource pooling.',
    descriptionZh: 'SaaS 多租户 ER 图，含租户隔离和共享资源池设计。',
  },
  {
    id: 'w8',
    title: 'IoT Sensor Pipeline',
    titleZh: 'IoT 传感器管道',
    author: 'EdgeTech',
    avatarColor: 'bg-teal-500',
    diagramType: 'flowchart',
    industry: 'iot',
    complexity: 'medium',
    cloneCount: 167,
    viewCount: 940,
    createdAt: '2026-02-17',
    agentVersion: 'v2.1',
    thumbnailSize: 'sm',
    thumbnail: {
      viewBox: '0 0 280 120',
      nodes: [
        { x: 10, y: 46, w: 46, h: 24, rx: 6, color: EMERALD, label: 'Sensors', delay: 0 },
        { x: 74, y: 46, w: 46, h: 24, rx: 6, color: B5, label: 'MQTT', delay: 1 },
        { x: 138, y: 46, w: 46, h: 24, rx: 6, color: B6, label: 'Process', delay: 2 },
        { x: 202, y: 46, w: 46, h: 24, rx: 6, color: AMBER, label: 'Storage', delay: 3 },
      ],
      edges: [
        { d: 'M56 58 L74 58', color: SLATE3, delay: 0 },
        { d: 'M120 58 L138 58', color: SLATE3, delay: 1 },
        { d: 'M184 58 L202 58', color: SLATE3, delay: 2 },
      ],
    },
    description: 'Edge-to-cloud IoT data pipeline with MQTT broker, stream processing, and time-series storage.',
    descriptionZh: '边缘到云端 IoT 数据管道，含 MQTT 代理、流处理和时序存储。',
  },
  {
    id: 'w9',
    title: 'Fraud Detection State Machine',
    titleZh: '欺诈检测状态机',
    author: 'SecureBank',
    avatarColor: 'bg-orange-500',
    diagramType: 'stateDiagram',
    industry: 'fintech',
    complexity: 'medium',
    cloneCount: 223,
    viewCount: 1350,
    createdAt: '2026-02-21',
    agentVersion: 'v2.2',
    thumbnailSize: 'md',
    thumbnail: {
      viewBox: '0 0 280 160',
      nodes: [
        { x: 20, y: 65, w: 56, h: 28, rx: 14, color: EMERALD, label: 'Received', delay: 0 },
        { x: 110, y: 20, w: 56, h: 28, rx: 14, color: B5, label: 'Verified', delay: 1 },
        { x: 110, y: 110, w: 56, h: 28, rx: 14, color: AMBER, label: 'Review', delay: 2 },
        { x: 200, y: 65, w: 56, h: 28, rx: 14, color: ROSE, label: 'Resolved', delay: 3 },
      ],
      edges: [
        { d: 'M76 72 L110 34', color: SLATE3, delay: 0 },
        { d: 'M76 86 L110 124', color: SLATE3, delay: 1 },
        { d: 'M166 34 L200 72', color: SLATE3, delay: 2 },
        { d: 'M166 124 L200 86', color: SLATE3, delay: 3 },
      ],
    },
    description: 'State machine for real-time fraud detection with risk scoring and escalation paths.',
    descriptionZh: '实时欺诈检测状态机，含风险评分和升级路径。',
  },
  {
    id: 'w10',
    title: 'Telemedicine Swimlane',
    titleZh: '远程医疗泳道图',
    author: 'MediFlow',
    avatarColor: 'bg-cyan-500',
    diagramType: 'swimlane',
    industry: 'healthcare',
    complexity: 'complex',
    cloneCount: 198,
    viewCount: 1080,
    createdAt: '2026-02-19',
    agentVersion: 'v2.2',
    thumbnailSize: 'lg',
    thumbnail: {
      viewBox: '0 0 280 156',
      nodes: [
        { x: 30, y: 15, w: 220, h: 1, rx: 0, color: SLATE3, delay: 0 },
        { x: 30, y: 50, w: 220, h: 1, rx: 0, color: SLATE3, delay: 0 },
        { x: 30, y: 99, w: 220, h: 1, rx: 0, color: SLATE3, delay: 0 },
        { x: 50, y: 22, w: 48, h: 16, rx: 6, color: B5, label: 'Book', delay: 1 },
        { x: 130, y: 22, w: 48, h: 16, rx: 6, color: B4, label: 'Join', delay: 2 },
        { x: 50, y: 58, w: 48, h: 16, rx: 6, color: EMERALD, label: 'Consult', delay: 3 },
        { x: 130, y: 58, w: 48, h: 16, rx: 6, color: AMBER, label: 'Diagnose', delay: 4 },
        { x: 50, y: 109, w: 48, h: 16, rx: 6, color: VIOLET, label: 'Bill', delay: 5 },
        { x: 180, y: 109, w: 48, h: 16, rx: 6, color: ROSE, label: 'Archive', delay: 6 },
      ],
      edges: [
        { d: 'M98 31 L130 31', color: SLATE3, delay: 1 },
        { d: 'M98 67 L130 67', color: SLATE3, delay: 2 },
        { d: 'M98 117 L180 117', color: SLATE3, delay: 3 },
      ],
    },
    description: 'Cross-department telemedicine workflow showing patient, doctor, and admin interactions.',
    descriptionZh: '跨部门远程医疗工作流，展示患者、医生和管理员交互。',
  },
  {
    id: 'w11',
    title: 'Microservice Deployment',
    titleZh: '微服务部署架构',
    author: 'Kube Team',
    avatarColor: 'bg-sky-500',
    diagramType: 'architecture',
    industry: 'devops',
    complexity: 'complex',
    cloneCount: 389,
    viewCount: 2100,
    createdAt: '2026-02-26',
    agentVersion: 'v2.3',
    thumbnailSize: 'md',
    thumbnail: {
      viewBox: '0 0 280 160',
      nodes: [
        { x: 100, y: 10, w: 80, h: 24, rx: 6, color: B5, label: 'Ingress', delay: 0 },
        { x: 20, y: 65, w: 56, h: 24, rx: 6, color: B4, label: 'Service A', delay: 1 },
        { x: 112, y: 65, w: 56, h: 24, rx: 6, color: EMERALD, label: 'Service B', delay: 2 },
        { x: 204, y: 65, w: 56, h: 24, rx: 6, color: AMBER, label: 'Service C', delay: 3 },
        { x: 100, y: 125, w: 80, h: 24, rx: 6, color: VIOLET, label: 'Telemetry', delay: 4 },
      ],
      edges: [
        { d: 'M140 34 L48 65', color: SLATE3, delay: 0 },
        { d: 'M140 34 L140 65', color: SLATE3, delay: 1 },
        { d: 'M140 34 L232 65', color: SLATE3, delay: 2 },
        { d: 'M48 89 L140 125', color: SLATE3, delay: 3 },
        { d: 'M232 89 L140 125', color: SLATE3, delay: 4 },
      ],
    },
    description: 'Kubernetes-based microservice deployment topology with service mesh, ingress, and observability.',
    descriptionZh: '基于 Kubernetes 的微服务部署拓扑，含服务网格、入口和可观测性。',
  },
  {
    id: 'w12',
    title: 'Learning Path Gantt Chart',
    titleZh: '学习路径甘特图',
    author: 'SkillUp',
    avatarColor: 'bg-lime-600',
    diagramType: 'gantt',
    industry: 'education',
    complexity: 'simple',
    cloneCount: 98,
    viewCount: 620,
    createdAt: '2026-02-10',
    agentVersion: 'v2.0',
    thumbnailSize: 'sm',
    thumbnail: {
      viewBox: '0 0 280 120',
      nodes: [
        { x: 20, y: 20, w: 120, h: 16, rx: 4, color: B5, label: 'Foundations', delay: 0 },
        { x: 60, y: 46, w: 100, h: 16, rx: 4, color: EMERALD, label: 'Practice', delay: 1 },
        { x: 100, y: 72, w: 140, h: 16, rx: 4, color: AMBER, label: 'Projects', delay: 2 },
        { x: 160, y: 98, w: 100, h: 16, rx: 4, color: VIOLET, label: 'Certification', delay: 3 },
      ],
      edges: [],
    },
    description: 'Gantt chart for structured online learning path with dependencies and milestones.',
    descriptionZh: '结构化在线学习路径甘特图，含依赖关系和里程碑。',
  },
];

// ─── 6 Mock DNA ───────────────────────────
export const GALLERY_DNA: GalleryDna[] = [
  {
    id: 'd1',
    name: 'Enterprise VI Standard',
    nameZh: '企业 VI 标准',
    author: 'DesignOps',
    avatarColor: 'bg-blue-600',
    injectCount: 526,
    category: 'style',
    variants: [
      { label: 'Light', labelZh: '浅色', previewColors: ['#318dff', '#e2e8f0', '#f8fafc'] },
      { label: 'Dark', labelZh: '深色', previewColors: ['#52aeff', '#1e293b', '#0f172a'] },
      { label: 'High Contrast', labelZh: '高对比', previewColors: ['#1e6ef5', '#000000', '#ffffff'] },
    ],
    description: 'Standard enterprise visual identity gene — consistent branding across all generated diagrams.',
    descriptionZh: '标准企业视觉识别基因 — 所有生成图表保持品牌一致性。',
    tags: ['corporate', 'brand', 'consistent'],
    tagsZh: ['企业', '品牌', '一致性'],
  },
  {
    id: 'd2',
    name: 'Minimal Structure',
    nameZh: '极简结构',
    author: 'MinimalStudio',
    avatarColor: 'bg-slate-600',
    injectCount: 412,
    category: 'structure',
    variants: [
      { label: 'Clean', labelZh: '干净', previewColors: ['#64748b', '#e2e8f0', '#ffffff'] },
      { label: 'Airy', labelZh: '宽松', previewColors: ['#94a3b8', '#f1f5f9', '#ffffff'] },
      { label: 'Dense', labelZh: '紧凑', previewColors: ['#475569', '#cbd5e1', '#f8fafc'] },
    ],
    description: 'Reduces visual noise by enforcing minimal node counts and clean hierarchy.',
    descriptionZh: '通过限制节点数量和保持干净层级来减少视觉噪音。',
    tags: ['minimal', 'clean', 'hierarchy'],
    tagsZh: ['极简', '干净', '层级'],
  },
  {
    id: 'd3',
    name: 'Hand-drawn Sketch',
    nameZh: '手绘风格',
    author: 'SketchPad',
    avatarColor: 'bg-amber-500',
    injectCount: 337,
    category: 'style',
    variants: [
      { label: 'Pencil', labelZh: '铅笔', previewColors: ['#78716c', '#fafaf9', '#ffffff'] },
      { label: 'Marker', labelZh: '马克笔', previewColors: ['#f59e0b', '#fffbeb', '#ffffff'] },
      { label: 'Ink', labelZh: '墨水', previewColors: ['#1c1917', '#f5f5f4', '#ffffff'] },
    ],
    description: 'Gives diagrams a casual, hand-drawn aesthetic perfect for brainstorming and ideation.',
    descriptionZh: '赋予图表休闲手绘美感，非常适合头脑风暴和创意构思。',
    tags: ['sketch', 'casual', 'brainstorm'],
    tagsZh: ['手绘', '休闲', '头脑风暴'],
  },
  {
    id: 'd4',
    name: 'LR-First Layout',
    nameZh: '水平优先布局',
    author: 'LayoutPro',
    avatarColor: 'bg-emerald-500',
    injectCount: 289,
    category: 'layout',
    variants: [
      { label: 'Compact', labelZh: '紧凑', previewColors: ['#10b981', '#d1fae5', '#ecfdf5'] },
      { label: 'Standard', labelZh: '标准', previewColors: ['#059669', '#a7f3d0', '#d1fae5'] },
      { label: 'Spacious', labelZh: '宽松', previewColors: ['#047857', '#6ee7b7', '#a7f3d0'] },
    ],
    description: 'Enforces left-to-right flow direction with optimized spacing for horizontal readability.',
    descriptionZh: '强制左到右流向，优化水平间距以提升可读性。',
    tags: ['LR', 'horizontal', 'spacing'],
    tagsZh: ['水平', '横向', '间距'],
  },
  {
    id: 'd5',
    name: 'Neon Night',
    nameZh: '霓虹夜色',
    author: 'NightOwl',
    avatarColor: 'bg-violet-500',
    injectCount: 245,
    category: 'style',
    variants: [
      { label: 'Cyber', labelZh: '赛博', previewColors: ['#a78bfa', '#1e1b4b', '#0f0a2e'] },
      { label: 'Miami', labelZh: '迈阿密', previewColors: ['#f472b6', '#1e1b4b', '#0f172a'] },
      { label: 'Matrix', labelZh: '矩阵', previewColors: ['#4ade80', '#052e16', '#022c22'] },
    ],
    description: 'Bold neon colors on dark backgrounds — ideal for presentations and demos.',
    descriptionZh: '深色背景上的大胆霓虹色彩 — 非常适合演示和展示。',
    tags: ['neon', 'dark', 'presentation'],
    tagsZh: ['霓虹', '暗色', '演示'],
  },
  {
    id: 'd6',
    name: 'Dense Info-Pack',
    nameZh: '高密度信息包',
    author: 'DataDense',
    avatarColor: 'bg-rose-500',
    injectCount: 178,
    category: 'layout',
    variants: [
      { label: 'Ultra Dense', labelZh: '超密集', previewColors: ['#f43f5e', '#fda4af', '#fff1f2'] },
      { label: 'Balanced', labelZh: '均衡', previewColors: ['#e11d48', '#fb7185', '#fecdd3'] },
      { label: 'Hybrid', labelZh: '混合', previewColors: ['#be123c', '#f43f5e', '#fda4af'] },
    ],
    description: 'Maximizes information density while maintaining readability — best for complex systems.',
    descriptionZh: '在保持可读性的同时最大化信息密度 — 最适合复杂系统。',
    tags: ['dense', 'complex', 'info-rich'],
    tagsZh: ['密集', '复杂', '信息丰富'],
  },
];

// ─── Ranking Lists ────────────────────────
export const TRENDING_WORKS = GALLERY_WORKS
  .slice()
  .sort((a, b) => b.viewCount - a.viewCount)
  .slice(0, 5);

export const POPULAR_DNA = GALLERY_DNA
  .slice()
  .sort((a, b) => b.injectCount - a.injectCount)
  .slice(0, 5);

// ─── Filter Constants ─────────────────────
export const INDUSTRY_TAGS: IndustryTag[] = [
  'fintech',
  'healthcare',
  'ecommerce',
  'devops',
  'education',
  'gaming',
  'saas',
  'iot',
];

export const COMPLEXITY_TAGS: ComplexityTag[] = ['simple', 'medium', 'complex'];
