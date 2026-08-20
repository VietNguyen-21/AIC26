import React, { useEffect, useRef, useState, useCallback } from 'react'
import { useAppDispatch, useAppState } from '../state/AppContext'
import { getVideoStreamUrl, getThumbnailUrl } from '../api/tv4Client'
import { getFixturePreviewDataUri } from '../fixtures/fixtureData'
import { ExactNeighborThumb } from './ExactNeighborThumb'
import { CandidatePreviewThumb } from './CandidatePreviewThumb'
import { SearchCandidate } from '../types/contracts'
import {
  VideoIcon,
  FrameIcon,
  StepPrevIcon,
  StepNextIcon,
  AnchorIcon,
  CheckIcon,
  WarningIcon,
  SpinnerIcon,
  ArrowLeftIcon,
  QuestionIcon,
  FilmstripIcon,
  BasketIcon,
} from './Icons'
import { EvidenceInspector } from './EvidenceInspector'
import { VqaAnswerPanel } from './VqaAnswerPanel'
import { telemetry } from '../utils/telemetry'

export const InspectionWorkspace: React.FC = () => {
  const {
    activeCandidate,
    anchorCandidate,
    candidates,
    kisActiveCandidate,
    cumulativeOffset,
    isStepping,
    stepError,
    currentStep,
    exactNeighbors,
    exactImageBlobUrl,
    isImageLoading,
    imageError,
    mode,
    vqaResults,
    vqaActiveResult,
    queryText,
    vqaQuestion,
    taskMode,
    queryId,
    trakeSlots,
    trakeActiveSlotIndex,
    trakeVideoId,
    submissionBasket,
  } = useAppState()

  const dispatch = useAppDispatch()
  const videoRef = useRef<HTMLVideoElement>(null)
  const [playbackTime, setPlaybackTime] = useState<number>(0)
  const [frameImgFailed, setFrameImgFailed] = useState(false)
  const [showProofDetails, setShowProofDetails] = useState(false)
  const isFixture = mode === 'fixture'

  // Reset image error state when active candidate or offset changes
  useEffect(() => {
    setFrameImgFailed(false)
  }, [activeCandidate, cumulativeOffset])

  // Seek video when active candidate changes
  useEffect(() => {
    if (activeCandidate && videoRef.current) {
      const targetSec = activeCandidate.timestamp_ms / 1000
      videoRef.current.currentTime = targetSec
      setPlaybackTime(targetSec)
    }
  }, [activeCandidate])

  const handleTimeUpdate = () => {
    if (videoRef.current) {
      setPlaybackTime(videoRef.current.currentTime)
    }
  }

  // Exact stepping logic: dispatches step intent to single authoritative coordinator
  const handleStep = useCallback(
    (targetOffset: number) => {
      dispatch({ type: 'EXACT_STEP_START', payload: { offset: targetOffset } })
    },
    [dispatch]
  )

  // Keyboard navigation for stepping
  useEffect(() => {
    const handleKeyDown = (e: globalThis.KeyboardEvent) => {
      if (
        document.activeElement?.tagName === 'INPUT' ||
        document.activeElement?.tagName === 'TEXTAREA' ||
        document.activeElement?.tagName === 'SELECT'
      ) {
        return
      }

      if (e.key === 'ArrowLeft') {
        e.preventDefault()
        handleStep(cumulativeOffset - 1)
      } else if (e.key === 'ArrowRight') {
        e.preventDefault()
        handleStep(cumulativeOffset + 1)
      } else if (e.key === 'Home' || e.key === '0') {
        e.preventDefault()
        handleStep(0)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [cumulativeOffset, handleStep])

  const activeTrakeSlot =
    trakeActiveSlotIndex !== null && trakeActiveSlotIndex < trakeSlots.length
      ? trakeSlots[trakeActiveSlotIndex]
      : null

  const handlePrevTrakeEvent = () => {
    if (trakeActiveSlotIndex === null || trakeActiveSlotIndex <= 0) return
    const newIdx = trakeActiveSlotIndex - 1
    dispatch({ type: 'SELECT_TRAKE_SLOT', payload: newIdx })
  }

  const handleNextTrakeEvent = () => {
    if (trakeActiveSlotIndex === null || trakeActiveSlotIndex >= trakeSlots.length - 1) return
    const newIdx = trakeActiveSlotIndex + 1
    dispatch({ type: 'SELECT_TRAKE_SLOT', payload: newIdx })
  }

  const targetCandidate: SearchCandidate | null =
    taskMode === 'TRAKE'
      ? activeTrakeSlot && activeTrakeSlot.video_id && activeTrakeSlot.frame_id !== null
        ? {
            query_id: queryId || 'trake',
            video_id: activeTrakeSlot.video_id,
            frame_id: activeTrakeSlot.frame_id,
            timestamp_ms: activeTrakeSlot.timestamp_ms || 0,
            source: 'trake',
            rank: activeTrakeSlot.event_index + 1,
            score: activeTrakeSlot.score,
            certified_anchor_frame_id: activeTrakeSlot.certified_anchor_frame_id ?? activeTrakeSlot.frame_id,
            certified_anchor_timestamp_ms: activeTrakeSlot.certified_anchor_timestamp_ms ?? activeTrakeSlot.timestamp_ms ?? 0,
            anchor_offset: activeTrakeSlot.anchor_offset ?? 0,
            cumulative_offset: 0,
          }
        : null
      : taskMode === 'VQA'
      ? vqaActiveResult
        ? {
            query_id: queryId || 'vqa',
            video_id: vqaActiveResult.video_id,
            frame_id: vqaActiveResult.frame_id,
            timestamp_ms: vqaActiveResult.timestamp_ms || 0,
            source: 'vqa',
            rank: vqaActiveResult.rank,
            score: vqaActiveResult.confidence,
            certified_anchor_frame_id: vqaActiveResult.certified_anchor_frame_id,
            certified_anchor_timestamp_ms: vqaActiveResult.certified_anchor_timestamp_ms,
            anchor_offset: vqaActiveResult.anchor_offset,
          }
        : null
      : kisActiveCandidate || (candidates.length > 0 ? candidates[0] : null)

  if (!targetCandidate) {
    return (
      <div className="inspection-workspace-empty" data-testid="workspace-empty">
        <div className="empty-message-box">
          <p className="empty-title">
            {taskMode === 'TRAKE'
              ? 'No TRAKE Event Frame Available for Inspection'
              : taskMode === 'VQA'
              ? 'No VQA Answer Selected for Inspection'
              : 'No Candidate Selected for Inspection'}
          </p>
          <p className="empty-subtitle">
            {taskMode === 'TRAKE'
              ? 'Run Search & Align in the Retrieval workspace to align event slots.'
              : taskMode === 'VQA'
              ? 'Run Search & Answer in the Retrieval workspace to generate grounded answers.'
              : 'Perform a search in the Retrieval tab and select a candidate to inspect.'}
          </p>
          <button
            type="button"
            className="return-retrieval-btn"
            onClick={() => dispatch({ type: 'SET_ACTIVE_TAB', payload: 'retrieval' })}
          >
            <ArrowLeftIcon size={14} />
            <span>Go to Retrieval</span>
          </button>
        </div>
      </div>
    )
  }

  const isCurrentStepMatching = currentStep?.frame?.video_id === targetCandidate.video_id

  const inspectedFrameId =
    cumulativeOffset === 0 && (!currentStep?.frame || !isCurrentStepMatching)
      ? targetCandidate.frame_id
      : isCurrentStepMatching
      ? currentStep?.frame?.frame_id
      : targetCandidate.frame_id

  const inspectedTimestampMs =
    cumulativeOffset === 0 && (!currentStep?.frame || !isCurrentStepMatching)
      ? targetCandidate.timestamp_ms
      : isCurrentStepMatching
      ? currentStep?.frame?.timestamp_ms
      : targetCandidate.timestamp_ms

  const isSelectable = isFixture
    ? false
    : cumulativeOffset === 0
    ? true
    : isCurrentStepMatching && currentStep?.frame?.submission_selectable === true

  const isBoundary =
    currentStep && (!currentStep.frame || currentStep.degraded_reason !== null)

  const videoStreamUrl = getVideoStreamUrl(targetCandidate.video_id)

  const handleSelectCandidate = (cand: SearchCandidate) => {
    dispatch({ type: 'SELECT_CANDIDATE', payload: cand })
  }

  return (
    <div className="inspection-workspace-layout" data-testid="inspection-workspace">
      {/* ── 1. Left Candidate Shortlist Column (~235px) ── */}
      <aside className="inspection-shortlist-rail" data-testid="inspection-shortlist-rail">
        <div className="shortlist-header">
          <span className="shortlist-title tabular-nums">
            {taskMode === 'TRAKE'
              ? `Event Slots (${trakeSlots.length})`
              : taskMode === 'VQA'
              ? `VQA Answers (${vqaResults.length})`
              : `Results (${candidates.length})`}
          </span>
          <button
            type="button"
            className="back-to-retrieval-link"
            onClick={() => dispatch({ type: 'SET_ACTIVE_TAB', payload: 'retrieval' })}
            title="Return to retrieval results"
          >
            <ArrowLeftIcon size={12} />
            <span>Back to Results</span>
          </button>
        </div>

        <div className="shortlist-cards-scroll">
          {taskMode === 'TRAKE' ? (
            trakeSlots.map((slot) => {
              const isSelected = trakeActiveSlotIndex === slot.event_index
              const hasFrame = slot.video_id && slot.frame_id !== null
              const slotCand: SearchCandidate | null = hasFrame
                ? {
                    query_id: queryId || 'trake',
                    video_id: slot.video_id!,
                    frame_id: slot.frame_id!,
                    timestamp_ms: slot.timestamp_ms || 0,
                    source: 'trake',
                    rank: slot.event_index + 1,
                    score: slot.score,
                    certified_anchor_frame_id:
                      slot.certified_anchor_frame_id ?? slot.frame_id!,
                    certified_anchor_timestamp_ms:
                      slot.certified_anchor_timestamp_ms ?? slot.timestamp_ms ?? 0,
                    anchor_offset: slot.anchor_offset ?? 0,
                    cumulative_offset: 0,
                  }
                : null

              return (
                <div
                  key={`trake-slot-rail-${slot.event_index}`}
                  className={`shortlist-card ${isSelected ? 'card-selected' : ''}`}
                  onClick={() => {
                    dispatch({ type: 'SELECT_TRAKE_SLOT', payload: slot.event_index })
                  }}
                  role="button"
                  tabIndex={0}
                  data-testid={`trake-shortlist-card-${slot.event_index}`}
                >
                  <div className="shortlist-thumb-box">
                    {slotCand ? (
                      <CandidatePreviewThumb
                        candidate={slotCand}
                        alt={`Event ${slot.event_index + 1}`}
                        className="shortlist-thumb-img"
                        onErrorFallback={
                          <div className="shortlist-thumb-placeholder">
                            <span>#{slot.event_index + 1}</span>
                          </div>
                        }
                      />
                    ) : (
                      <div className="shortlist-thumb-placeholder">
                        <span>#{slot.event_index + 1}</span>
                      </div>
                    )}
                    <span className="shortlist-rank-tag tabular-nums">#{slot.event_index + 1}</span>
                  </div>

                  <div className="shortlist-info">
                    <span className="shortlist-vid" title={slot.event_label}>{slot.event_label}</span>
                    <span className="shortlist-fid tabular-nums">
                      {slot.frame_id !== null ? `Frame ${slot.frame_id}` : 'Unassigned'}
                    </span>
                    <div className="shortlist-sub-meta">
                      {slot.score != null && (
                        <span className="shortlist-score tabular-nums text-cyan">
                          {slot.score.toFixed(3)}
                        </span>
                      )}
                      <span className={`slot-rail-lock-badge ${slot.locked ? 'is-locked' : 'is-unlocked'}`}>
                        {slot.locked ? 'LOCKED' : 'UNLOCKED'}
                      </span>
                    </div>
                    {isSelected && <span className="shortlist-anchor-pill">Active</span>}
                  </div>
                </div>
              )
            })
          ) : taskMode === 'VQA' ? (
            vqaResults.length === 0 ? (
              <div className="shortlist-empty-note">
                <span>No VQA answers yet</span>
              </div>
            ) : (
              vqaResults.map((res) => {
                const isSelected =
                  vqaActiveResult?.video_id === res.video_id &&
                  vqaActiveResult?.frame_id === res.frame_id
                const formattedRank = res.rank < 10 ? `0${res.rank}` : `${res.rank}`
                const vqaCand: SearchCandidate = {
                  query_id: queryId || 'vqa',
                  video_id: res.video_id,
                  frame_id: res.frame_id,
                  timestamp_ms: res.timestamp_ms || 0,
                  source: 'vqa',
                  rank: res.rank,
                  score: res.confidence,
                  certified_anchor_frame_id: res.certified_anchor_frame_id,
                  certified_anchor_timestamp_ms: res.certified_anchor_timestamp_ms,
                  anchor_offset: res.anchor_offset,
                }

                return (
                  <div
                    key={`vqa-rail-${res.video_id}-${res.frame_id}-${res.rank}`}
                    className={`shortlist-card ${isSelected ? 'card-selected' : ''}`}
                    onClick={() => dispatch({ type: 'SELECT_VQA_RESULT', payload: res })}
                    role="button"
                    tabIndex={0}
                    data-testid={`vqa-shortlist-card-${res.rank}`}
                  >
                    <div className="shortlist-thumb-box">
                      <CandidatePreviewThumb
                        candidate={vqaCand}
                        alt={`Rank ${res.rank}`}
                        className="shortlist-thumb-img"
                      />
                      <span className="shortlist-rank-tag tabular-nums">{formattedRank}</span>
                    </div>

                    <div className="shortlist-info">
                      <span className="shortlist-vid">{res.video_id}</span>
                      <span className="shortlist-fid tabular-nums">Frame {res.frame_id}</span>
                      <div className="shortlist-sub-meta">
                        <span className="shortlist-score tabular-nums text-cyan">
                          {res.confidence != null ? `${(res.confidence * 100).toFixed(0)}%` : ''}
                        </span>
                      </div>
                      {isSelected && <span className="shortlist-anchor-pill">Active</span>}
                    </div>
                  </div>
                )
              })
            )
          ) : (
            candidates.map((cand) => {
              const isSelected =
                targetCandidate.video_id === cand.video_id &&
                targetCandidate.frame_id === cand.frame_id
              const formattedRank = cand.rank < 10 ? `0${cand.rank}` : `${cand.rank}`

              return (
                <div
                  key={`${cand.video_id}-${cand.frame_id}-${cand.rank}`}
                  className={`shortlist-card ${isSelected ? 'card-selected' : ''}`}
                  onClick={() => handleSelectCandidate(cand)}
                  role="button"
                  tabIndex={0}
                  data-testid={`shortlist-card-${cand.rank}`}
                >
                  <div className="shortlist-thumb-box">
                    <CandidatePreviewThumb
                      candidate={cand}
                      alt={`Rank ${cand.rank}`}
                      className="shortlist-thumb-img"
                      loading="lazy"
                      onErrorFallback={<span className="shortlist-thumb-fallback">N/A</span>}
                    />
                    <span className="shortlist-rank-tag tabular-nums">{formattedRank}</span>
                  </div>

                  <div className="shortlist-info">
                    <span className="shortlist-vid">{cand.video_id}</span>
                    <span className="shortlist-fid tabular-nums">Frame {cand.frame_id}</span>
                    {cand.score != null && (
                      <span className="shortlist-score tabular-nums text-cyan">
                        {cand.score.toFixed(4)}
                      </span>
                    )}
                    {isSelected && <span className="shortlist-anchor-pill">Anchor</span>}
                  </div>
                </div>
              )
            })
          )}
        </div>
      </aside>

      {/* ── 2. Center Media Stage ── */}
      <main className="inspection-media-stage">
        {/* Top Context Strip for TRAKE Mode */}
        {taskMode === 'TRAKE' && (
          <div className="inspection-trake-context-strip" data-testid="inspection-context-strip">
            <div className="context-strip-task-tag trake-tag">
              <FilmstripIcon size={14} className="text-cyan" />
              <span>TRAKE</span>
            </div>

            <div className="context-strip-item">
              <span className="context-strip-label">Sequence:</span>
              <span className="context-strip-value" data-testid="context-strip-event">
                {queryText || 'N/A'}
              </span>
            </div>

            <div className="context-strip-item highlight-trake-event">
              <span className="context-strip-label">Active Event:</span>
              <span className="context-strip-value" data-testid="trake-context-event">
                {activeTrakeSlot
                  ? `Event #${activeTrakeSlot.event_index + 1} of ${trakeSlots.length}: "${activeTrakeSlot.event_label}"`
                  : 'None'}
              </span>
            </div>

            <div className="context-strip-item">
              <span className="context-strip-label">Hypothesis:</span>
              <span className="context-strip-value text-cyan tabular-nums" data-testid="trake-context-video">
                {trakeVideoId || targetCandidate.video_id}
              </span>
            </div>

            <div className="context-strip-item">
              <span className="context-strip-label">Status:</span>
              <span
                className={`context-strip-badge ${activeTrakeSlot?.locked ? 'badge-locked' : 'badge-unlocked'}`}
                data-testid="trake-context-lock"
              >
                {activeTrakeSlot?.locked ? 'LOCKED' : 'UNLOCKED'}
              </span>
            </div>

            {/* Event Navigation (Previous / Next Event in Sequence) */}
            <div className="context-strip-event-nav" data-testid="trake-event-nav">
              <button
                type="button"
                className="btn-event-nav"
                disabled={trakeActiveSlotIndex === null || trakeActiveSlotIndex <= 0}
                onClick={handlePrevTrakeEvent}
                title="Navigate to previous semantic event in sequence"
                data-testid="btn-trake-prev-event"
              >
                ← Prev Event
              </button>

              <button
                type="button"
                className="btn-event-nav"
                disabled={
                  trakeActiveSlotIndex === null ||
                  trakeActiveSlotIndex >= trakeSlots.length - 1
                }
                onClick={handleNextTrakeEvent}
                title="Navigate to next semantic event in sequence"
                data-testid="btn-trake-next-event"
              >
                Next Event →
              </button>
            </div>
          </div>
        )}

        {/* Top Context Strip for Q&A Mode */}
        {taskMode === 'VQA' && (
          <div className="inspection-vqa-context-strip" data-testid="inspection-context-strip">
            <div className="context-strip-task-tag">
              <QuestionIcon size={14} className="text-cyan" />
              <span>Q&A</span>
            </div>
            <div className="context-strip-item">
              <span className="context-strip-label">Event:</span>
              <span className="context-strip-value" data-testid="context-strip-event">
                {queryText || vqaActiveResult?.evidence.query_text || 'N/A'}
              </span>
            </div>
            <div className="context-strip-item highlight-q">
              <span className="context-strip-label">Question:</span>
              <span className="context-strip-value" data-testid="context-strip-question">
                {vqaQuestion || vqaActiveResult?.evidence.question || 'N/A'}
              </span>
            </div>
          </div>
        )}

        {/* Dual Video & Frame Viewports */}
        <div className="viewports-split-row">
          {/* A. Original Video Context */}
          <div className="viewport-panel video-viewport">
            <div className="viewport-panel-header">
              <div className="panel-title-group">
                <VideoIcon size={16} className="text-cyan" />
                <span className="panel-title-text">Original Video</span>
              </div>
              <span className="panel-timecode tabular-nums">{playbackTime.toFixed(3)}s</span>
            </div>

            <div className="video-player-frame">
              <video
                ref={videoRef}
                src={videoStreamUrl}
                controls
                preload="metadata"
                onTimeUpdate={handleTimeUpdate}
                className="media-video-player"
                data-testid="original-video-player"
              />
            </div>
          </div>

          {/* B. Exact Canonical Frame */}
          <div className="viewport-panel frame-viewport">
            <div className="viewport-panel-header">
              <div className="panel-title-group">
                <FrameIcon size={16} className="text-cyan" />
                <span className="panel-title-text">Exact Canonical Frame</span>
              </div>

              <span
                className={`selectability-badge ${
                  isBoundary
                    ? 'badge-boundary'
                    : isSelectable
                    ? 'badge-selectable'
                    : isFixture
                    ? 'badge-fixture-preview'
                    : 'badge-non-selectable'
                }`}
                data-testid="submission-selectable-badge"
              >
                {isBoundary ? (
                  <>
                    <WarningIcon size={12} /> Boundary
                  </>
                ) : isSelectable ? (
                  <>
                    <CheckIcon size={12} /> Selectable
                  </>
                ) : isFixture ? (
                  <>
                    <WarningIcon size={12} /> Preview
                  </>
                ) : (
                  <>
                    <WarningIcon size={12} /> Non-Selectable
                  </>
                )}
              </span>
            </div>

            <div className="exact-frame-image-stage">
              {isImageLoading && (
                <div className="frame-loading-curtain">
                  <SpinnerIcon size={24} className="icon-spin text-cyan" />
                  <span>Decoding frame PTS...</span>
                </div>
              )}

              {!frameImgFailed && exactImageBlobUrl ? (
                <img
                  src={exactImageBlobUrl}
                  alt={`Exact frame ${inspectedFrameId}`}
                  className="exact-frame-img"
                  data-testid="exact-frame-image"
                  decoding="async"
                  onError={() => setFrameImgFailed(true)}
                />
              ) : !frameImgFailed && isFixture ? (
                <img
                  src={getFixturePreviewDataUri(
                    targetCandidate.video_id,
                    inspectedFrameId ?? targetCandidate.frame_id
                  )}
                  alt={`Exact frame ${inspectedFrameId}`}
                  className="exact-frame-img"
                  data-testid="exact-frame-image"
                  decoding="async"
                  onError={() => setFrameImgFailed(true)}
                />
              ) : (
                <div className="frame-error-matte">
                  <span>Exact frame preview unavailable</span>
                  <span className="tabular-nums">Frame {inspectedFrameId ?? 'UNKNOWN'}</span>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* C. Exact Neighbors Filmstrip (Bottom) */}
        <div className="exact-neighbors-panel" data-testid="context-strip">
          <div className="neighbors-panel-header">
            <div className="header-title-group">
              <span className="neighbors-title">
                Exact Canonical Neighbors
              </span>
            </div>

            {/* Stepping Transport Controls (NO -1 / +1 text) */}
            <div className="neighbors-transport-controls">
              <button
                type="button"
                className="step-btn"
                onClick={() => handleStep(cumulativeOffset - 1)}
                disabled={isStepping}
                data-testid="btn-step-prev"
                title="Step previous frame (Left Arrow)"
              >
                <StepPrevIcon size={14} />
                <span>Prev</span>
              </button>

              <button
                type="button"
                className="step-btn anchor-btn"
                onClick={() => handleStep(0)}
                disabled={isStepping || cumulativeOffset === 0}
                data-testid="btn-step-anchor"
                title="Reset to anchor (Home / 0)"
              >
                <AnchorIcon size={14} />
                <span>Anchor</span>
              </button>

              <button
                type="button"
                className="step-btn"
                onClick={() => handleStep(cumulativeOffset + 1)}
                disabled={isStepping}
                data-testid="btn-step-next"
                title="Step next frame (Right Arrow)"
              >
                <span>Next</span>
                <StepNextIcon size={14} />
              </button>

              <div
                className="offset-indicator-chip tabular-nums text-cyan"
                data-testid="cumulative-offset"
              >
                {cumulativeOffset === 0
                  ? '0'
                  : cumulativeOffset > 0
                  ? `+${cumulativeOffset}`
                  : `${cumulativeOffset}`}
              </div>

              {/* Exact Canonical Commit Button for KIS */}
              {taskMode === 'KIS' && inspectedFrameId !== undefined && inspectedFrameId !== targetCandidate.frame_id && (
                <button
                  type="button"
                  className="btn-use-for-event"
                  onClick={() => {
                    if (inspectedFrameId === undefined) return
                    const proof = currentStep?.frame ?? undefined
                    dispatch({
                      type: 'COMMIT_KIS_FRAME',
                      payload: {
                        frame_id: inspectedFrameId,
                        timestamp_ms: inspectedTimestampMs,
                        proof,
                      },
                    })
                  }}
                  title={`Commit Frame ${inspectedFrameId} as canonical prediction for ${targetCandidate.video_id}`}
                  data-testid="kis-set-canonical-frame-btn"
                >
                  <CheckIcon size={13} />
                  <span>Use This Frame</span>
                </button>
              )}

              {/* Add to Submission Basket Button for KIS */}
              {taskMode === 'KIS' && (() => {
                const finalFid = inspectedFrameId ?? targetCandidate.frame_id
                const isInBasket = submissionBasket.some(
                  (b) => b.video_id === targetCandidate.video_id && b.frame_id === finalFid && b.task === 'KIS'
                )
                return (
                  <button
                    type="button"
                    className="btn-use-for-event"
                    onClick={() => {
                      const finalTime = inspectedTimestampMs ?? targetCandidate.timestamp_ms
                      dispatch({
                        type: 'ADD_KIS_TO_BASKET',
                        payload: {
                          candidate: {
                            ...targetCandidate,
                            frame_id: finalFid,
                            timestamp_ms: finalTime,
                          },
                        },
                      })
                      telemetry.record({
                        action: 'ADD_KIS_TO_BASKET_FROM_INSPECTION',
                        taskMode: 'KIS',
                        videoId: targetCandidate.video_id,
                        frameId: finalFid,
                      })
                    }}
                    title={isInBasket ? `In Submission Basket (${targetCandidate.video_id} Frame ${finalFid})` : `Add ${targetCandidate.video_id} Frame ${finalFid} to Submission Basket`}
                    data-testid="inspection-add-to-basket-btn"
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '5px',
                      background: isInBasket ? 'rgba(16, 185, 129, 0.22)' : 'rgba(0, 229, 255, 0.15)',
                      borderColor: isInBasket ? '#10b981' : 'var(--color-cyan, #00e5ff)',
                      color: isInBasket ? '#10b981' : 'var(--color-cyan, #00e5ff)',
                      transition: 'all 0.2s cubic-bezier(0.16, 1, 0.3, 1)',
                    }}
                  >
                    {isInBasket ? <CheckIcon size={13} color="#10b981" /> : <BasketIcon size={13} />}
                    <span>{isInBasket ? 'In Basket' : '+ Basket'}</span>
                  </button>
                )
              })()}

              {/* Exact Canonical Commit Button for Q&A / VQA */}
              {taskMode === 'VQA' && inspectedFrameId !== undefined && inspectedFrameId !== targetCandidate.frame_id && (
                <button
                  type="button"
                  className="btn-use-for-event"
                  onClick={() => {
                    if (inspectedFrameId === undefined) return
                    const proof = currentStep?.frame ?? undefined
                    dispatch({
                      type: 'COMMIT_VQA_FRAME',
                      payload: {
                        frame_id: inspectedFrameId,
                        timestamp_ms: inspectedTimestampMs,
                        proof,
                      },
                    })
                  }}
                  title={`Set Frame ${inspectedFrameId} as authoritative answer frame for this prediction`}
                  data-testid="vqa-set-answer-frame-btn"
                >
                  <CheckIcon size={13} />
                  <span>Use as Answer Frame</span>
                </button>
              )}

              {/* Exact Canonical Correction Button for TRAKE */}
              {taskMode === 'TRAKE' && trakeActiveSlotIndex !== null && (
                <button
                  type="button"
                  className={`btn-use-for-event ${activeTrakeSlot?.locked ? 'is-locked-disabled' : ''}`}
                  onClick={() => {
                    if (
                      trakeActiveSlotIndex === null ||
                      inspectedFrameId === undefined ||
                      activeTrakeSlot?.locked
                    ) {
                      return
                    }
                    const proof = currentStep?.frame ?? undefined
                    dispatch({
                      type: 'CORRECT_TRAKE_SLOT',
                      payload: {
                        event_index: trakeActiveSlotIndex,
                        frame_id: inspectedFrameId,
                        timestamp_ms: inspectedTimestampMs,
                        proof,
                      },
                    })
                  }}
                  disabled={activeTrakeSlot?.locked || inspectedFrameId === undefined}
                  title={
                    activeTrakeSlot?.locked
                      ? 'Active event slot is locked. Unlock in timeline before setting frame.'
                      : `Set frame ${inspectedFrameId} for Event #${trakeActiveSlotIndex + 1} (${activeTrakeSlot?.event_label})`
                  }
                  data-testid="trake-set-event-frame-btn"
                >
                  <CheckIcon size={13} />
                  <span>Use for Event #{trakeActiveSlotIndex + 1}</span>
                </button>
              )}
            </div>
          </div>

          <div className="neighbors-thumbnails-track">
            {[-2, -1, 0, 1, 2].map((relOff) => {
              const effOff = cumulativeOffset + relOff
              const stepData = exactNeighbors?.steps?.find((s) => s.offset === effOff)
              const fid = stepData?.frame?.frame_id
              const isCurrent = effOff === cumulativeOffset
              const isAnchor = effOff === 0
              const isDegraded =
                !stepData || !stepData.frame || stepData.degraded_reason !== null

              return (
                <div
                  key={`neighbor-card-${effOff}`}
                  className={`neighbor-card ${isCurrent ? 'neighbor-current' : ''} ${
                    isAnchor ? 'neighbor-anchor' : ''
                  } ${isDegraded ? 'neighbor-degraded' : ''}`}
                  onClick={() => !isDegraded && handleStep(effOff)}
                  role="button"
                  tabIndex={0}
                  data-testid={`neighbor-card-${effOff}`}
                >
                  <div className="neighbor-thumb-box">
                    <ExactNeighborThumb
                      videoId={targetCandidate.video_id}
                      anchorFrameId={anchorCandidate?.frame_id ?? targetCandidate.frame_id}
                      anchorTimestampMs={anchorCandidate?.timestamp_ms ?? targetCandidate.timestamp_ms}
                      certifiedAnchorFrameId={
                        anchorCandidate?.certified_anchor_frame_id ??
                        targetCandidate.certified_anchor_frame_id ??
                        anchorCandidate?.frame_id ??
                        targetCandidate.frame_id
                      }
                      certifiedAnchorTimestampMs={
                        anchorCandidate?.certified_anchor_timestamp_ms ??
                        targetCandidate.certified_anchor_timestamp_ms ??
                        anchorCandidate?.timestamp_ms ??
                        targetCandidate.timestamp_ms
                      }
                      anchorOffset={anchorCandidate?.anchor_offset ?? targetCandidate.anchor_offset ?? 0}
                      cumulativeOffset={cumulativeOffset}
                      relOffset={relOff}
                      stepData={stepData}
                      isFixture={isFixture}
                    />
                  </div>
                  {/* Canonical frame_id label + semantic tags without offset notation */}
                  <div className="neighbor-meta tabular-nums">
                    <span className="meta-fid-title">
                      {stepData?.frame
                        ? `Frame ${fid}`
                        : !stepData
                        ? 'Loading...'
                        : 'Unavailable'}
                    </span>
                    {isAnchor && <span className="meta-role-pill pill-anchor">Anchor</span>}
                    {isCurrent && !isAnchor && (
                      <span className="meta-role-pill pill-current">Current</span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Main Q&A Working Region: ONLY rendered in VQA mode */}
        {taskMode === 'VQA' && (
          <div className="inspection-main-qa-region" data-testid="inspection-main-qa-region">
            <div className="qa-evidence-column">
              <EvidenceInspector evidence={vqaActiveResult?.evidence || null} />
            </div>
            <div className="qa-answer-column">
              <VqaAnswerPanel />
            </div>
          </div>
        )}
      </main>

      {/* ── 3. Right Technical Panel (~260px) ── */}
      <aside className="inspection-technical-panel" data-testid="canonical-identity-card">
        <div className="panel-header">
          <span className="panel-title">Proof & Identity</span>
        </div>

        <div className="tech-fields-grid">
          <div className="tech-field">
            <span className="field-label">Video ID</span>
            <span className="field-value text-cyan" data-testid="inspected-video-id">
              {targetCandidate.video_id}
            </span>
          </div>

          <div className="tech-field highlight-field">
            <span className="field-label">Frame ID</span>
            <span className="field-value tabular-nums" data-testid="inspected-frame-id">
              {inspectedFrameId ?? 'UNKNOWN'}
            </span>
          </div>

          <div className="tech-field">
            <span className="field-label">Timestamp</span>
            <span className="field-value tabular-nums" data-testid="inspected-timestamp-ms">
              {inspectedTimestampMs !== undefined ? `${inspectedTimestampMs} ms` : 'N/A'}
            </span>
          </div>

          <div className="tech-field">
            <span className="field-label">PTS</span>
            <span className="field-value tabular-nums">
              {currentStep?.frame?.pts ?? 'ANCHOR'}
            </span>
          </div>

          {taskMode === 'TRAKE' && activeTrakeSlot && (
            <div className="tech-field highlight-field" data-testid="trake-assigned-slot-box">
              <span className="field-label">Assigned Event</span>
              <span className="field-value text-cyan" data-testid="trake-slot-assigned-info">
                #{activeTrakeSlot.event_index + 1}: {activeTrakeSlot.event_label}
              </span>
            </div>
          )}
        </div>

        {/* Collapsible Technical Proof Details */}
        <div className="proof-details-disclosure">
          <button
            type="button"
            className="disclosure-toggle"
            onClick={() => setShowProofDetails(!showProofDetails)}
          >
            <span>{showProofDetails ? '▾ Hide Proof Details' : '▸ Technical Proof Details'}</span>
          </button>

          {showProofDetails && (
            <div className="disclosure-body tabular-nums">
              <div>Time Base: {currentStep?.frame?.time_base || '1/12800'}</div>
              <div>Run ID: {currentStep?.frame?.preprocess_run_id || 'run_v1_batch1'}</div>
              {currentStep?.frame?.certification_id && (
                <div>Cert ID: {currentStep.frame.certification_id}</div>
              )}
            </div>
          )}
        </div>

        {/* Warning Banner for Boundary / Degradation */}
        {(stepError || imageError || isBoundary) && (
          <div className="tech-alert-banner" data-testid="step-alert-banner">
            <WarningIcon size={14} />
            <span>
              {stepError || imageError || currentStep?.degraded_reason || 'Boundary reached'}
            </span>
          </div>
        )}
      </aside>
    </div>
  )
}
