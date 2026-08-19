import {
  BasketItem,
  ExactImageHeaders,
  ExactNeighborResponse,
  ExactStep,
  ReadinessStatus,
  SearchCandidate,
  SystemMode,
  TV4HealthResponse,
} from '../types/contracts'

export type WorkspaceTab = 'retrieval' | 'inspection' | 'evidence'
export type TaskMode = 'KIS' | 'VQA' | 'TRAKE'

export interface AppState {
  // Navigation
  activeTab: WorkspaceTab
  taskMode: TaskMode

  // System / Health / Readiness
  mode: SystemMode
  readiness: ReadinessStatus
  tv4Health: TV4HealthResponse | null
  healthError: string | null
  preprocessRunId: string | null

  // KIS Query & Results
  queryText: string
  queryId: string | null
  topK: number
  isSearching: boolean
  searchError: string | null
  candidates: SearchCandidate[]
  originalCandidates: SearchCandidate[]
  kisActiveCandidate: SearchCandidate | null

  // Feedback State (WP08 Composed Feedback Seam)
  feedbackSessionId: string | null
  feedbackOriginalQuery: string | null
  feedbackRevision: number
  feedbackActiveCount: number
  feedbackMaxEvents: number
  feedbackReference: SearchCandidate | null
  feedbackDraftText: string
  isFeedbackActive: boolean
  isFeedbackPending: boolean
  feedbackError: string | null
  feedbackExpiresAtUtc: string | null

  // Submission Basket (Isolated from Feedback)
  submissionBasket: BasketItem[]

  // VQA Workspace (WP11 / T016 / T030 / T031)
  vqaQuestion: string
  vqaResults: import('../types/contracts').VqaResult[]
  vqaActiveResult: import('../types/contracts').VqaResult | null
  vqaDraftAnswer: string
  vqaApprovedAnswer: string | null
  isVqaSearching: boolean
  vqaHasSearched: boolean
  vqaError: string | null

  // TRAKE Workspace (WP12 / T032 / T033)
  trakeEvents: string[]
  trakeSlots: import('../types/contracts').TrakeEventSlot[]
  trakeVideoId: string | null
  trakeActiveSlotIndex: number | null
  isTrakeSearching: boolean
  trakeHasSearched: boolean
  trakeError: string | null
  trakeAggregateScore: number | null
  trakeValidationStatus: 'valid' | 'incomplete' | 'mixed_video' | 'empty'

  // Inspection Workspace
  activeCandidate: SearchCandidate | null
  anchorCandidate: SearchCandidate | null
  cumulativeOffset: number
  isStepping: boolean
  stepError: string | null
  exactNeighbors: ExactNeighborResponse | null
  currentStep: ExactStep | null

  // Exact Image Rendering
  exactImageBlobUrl: string | null
  exactImageHeaders: ExactImageHeaders | null
  isImageLoading: boolean
  imageError: string | null
}

export const initialAppState: AppState = {
  activeTab: 'retrieval',
  taskMode: 'KIS',

  mode: 'live',
  readiness: 'OFFLINE',
  tv4Health: null,
  healthError: null,
  preprocessRunId: null,

  queryText: '',
  queryId: null,
  topK: 100,
  isSearching: false,
  searchError: null,
  candidates: [],
  originalCandidates: [],
  kisActiveCandidate: null,

  feedbackSessionId: null,
  feedbackOriginalQuery: null,
  feedbackRevision: 0,
  feedbackActiveCount: 0,
  feedbackMaxEvents: 5,
  feedbackReference: null,
  feedbackDraftText: '',
  isFeedbackActive: false,
  isFeedbackPending: false,
  feedbackError: null,
  feedbackExpiresAtUtc: null,

  submissionBasket: [],

  vqaQuestion: '',
  vqaResults: [],
  vqaActiveResult: null,
  vqaDraftAnswer: '',
  vqaApprovedAnswer: null,
  isVqaSearching: false,
  vqaHasSearched: false,
  vqaError: null,

  trakeEvents: [],
  trakeSlots: [],
  trakeVideoId: null,
  trakeActiveSlotIndex: null,
  isTrakeSearching: false,
  trakeHasSearched: false,
  trakeError: null,
  trakeAggregateScore: null,
  trakeValidationStatus: 'empty',

  activeCandidate: null,
  anchorCandidate: null,
  cumulativeOffset: 0,
  isStepping: false,
  stepError: null,
  exactNeighbors: null,
  currentStep: null,

  exactImageBlobUrl: null,
  exactImageHeaders: null,
  isImageLoading: false,
  imageError: null,
}
