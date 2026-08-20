import React from 'react'
import { useAppDispatch, useAppState } from '../state/AppContext'
import { EvidenceInspector } from './EvidenceInspector'
import { VqaAnswerPanel } from './VqaAnswerPanel'
import {
  EvidenceTabIcon,
  BasketIcon,
  ClearIcon,
  WarningIcon,
  CheckIcon,
  QuestionIcon,
  FilmstripIcon,
  ExportIcon,
} from './Icons'
import { exportBasketToCsvString, triggerBrowserDownload } from '../utils/submissionExporter'
import { telemetry } from '../utils/telemetry'

export const EvidenceSubmissionWorkspace: React.FC = () => {
  const {
    taskMode,
    vqaActiveResult,
    submissionBasket,
    mode,
    trakeSlots,
    trakeVideoId,
    trakeEvents,
    trakeValidationStatus,
    queryText,
    activeCandidate,
  } = useAppState()

  const dispatch = useAppDispatch()
  const isFixture = mode === 'fixture'

  const kisItems = submissionBasket.filter((b) => (b.task || 'KIS') === 'KIS')
  const vqaItems = submissionBasket.filter((b) => b.task === 'VQA')
  const trakeItems = submissionBasket.filter((b) => b.task === 'TRAKE')

  const currentTaskItems =
    taskMode === 'KIS' ? kisItems : taskMode === 'VQA' ? vqaItems : trakeItems
  const currentTaskLabel = taskMode === 'VQA' ? 'Q&A' : taskMode

  const handleRemoveFromBasket = (videoId: string, frameId: number) => {
    dispatch({
      type: 'REMOVE_FROM_BASKET',
      payload: { video_id: videoId, frame_id: frameId },
    })
    telemetry.record({
      action: 'REMOVE_FROM_BASKET',
      taskMode,
      videoId,
      frameId,
    })
  }

  const handleExportTaskCsv = (task: 'KIS' | 'VQA' | 'TRAKE') => {
    const items = submissionBasket.filter((b) => (b.task || 'KIS') === task)
    if (items.length === 0) return
    const csvContent = exportBasketToCsvString(submissionBasket, task)
    const filename = `submission_${task.toLowerCase()}_${new Date().toISOString().slice(0, 10)}.csv`
    triggerBrowserDownload(csvContent, filename)
    telemetry.record({
      action: 'EXPORT_SUBMISSION_CSV',
      taskMode: task,
      details: { rowCount: items.length, filename },
    })
  }

  const handleClearBasket = () => {
    dispatch({ type: 'CLEAR_BASKET' })
    telemetry.record({
      action: 'CLEAR_BASKET',
      taskMode,
    })
  }

  const activeEvidence = taskMode === 'VQA' ? vqaActiveResult?.evidence ?? null : null

  // TRAKE Readiness calculation
  const isTrakeAllLocked = trakeSlots.length > 0 && trakeSlots.every((s) => s.locked)
  const isTrakeStructurallyValid = trakeValidationStatus === 'valid'
  const isTrakeReady = isTrakeStructurallyValid && isTrakeAllLocked

  return (
    <div className="evidence-workspace-layout" data-testid="evidence-workspace">
      {/* Workspace Banner */}
      <div className="evidence-foundation-banner">
        <div className="banner-icon-box">
          <EvidenceTabIcon size={28} className="text-cyan" />
        </div>
        <div className="banner-text-block">
          <h2 className="banner-title">Evidence & Submission Management</h2>
          <p className="banner-description">
            Review multimodal proof, verify canonical candidates, adopt advisory proposals, and assemble competition submission packages.
          </p>
        </div>
      </div>

      {/* 2. Top Review Row (2-Column Decision Area: Task-Scoped Verification on Left ~59%, Submission Basket on Right ~41%) */}
      <div className="evidence-top-review-row">
        {/* Left Column: Task-Specific Review Panel */}
        <div className="evidence-review-left-col">
          {taskMode === 'VQA' ? (
            vqaActiveResult ? (
              <VqaAnswerPanel />
            ) : (
              <div className="evidence-card-notice" data-testid="no-vqa-notice">
                <div className="notice-icon-box">
                  <QuestionIcon size={20} className="text-cyan" />
                </div>
                <div className="notice-text-content">
                  <span className="notice-title">No Active VQA Query</span>
                  <p className="notice-text">
                    Enter a question in the Retrieval workspace to generate retrieval-grounded VQA answers and multimodal evidence.
                  </p>
                </div>
              </div>
            )
          ) : taskMode === 'TRAKE' ? (
            <div className="evidence-task-review-card" data-testid="evidence-trake-review">
              <div className="review-card-header">
                <div className="review-title-group">
                  <FilmstripIcon size={16} className="text-cyan" />
                  <span className="review-title">TRAKE Sequence Status</span>
                </div>
                <span
                  className={`trake-status-badge ${
                    isTrakeReady
                      ? 'badge-valid'
                      : isTrakeStructurallyValid
                      ? 'badge-aligned'
                      : 'badge-incomplete'
                  }`}
                >
                  {isTrakeReady
                    ? 'READY'
                    : isTrakeStructurallyValid
                    ? `ALIGNED (${trakeSlots.filter((s) => s.locked).length}/${trakeSlots.length} LOCKED)`
                    : 'INCOMPLETE'}
                </span>
              </div>
              <div className="review-card-body">
                <div className="review-field-row">
                  <span className="review-field-label">Sequence:</span>
                  <span className="review-field-val text-primary">{queryText || 'No sequence text'}</span>
                </div>
                <div className="review-field-row">
                  <span className="review-field-label">Video Hypothesis:</span>
                  <span className="review-field-val text-cyan tabular-nums">{trakeVideoId || 'Unassigned'}</span>
                </div>
                <div className="review-field-row">
                  <span className="review-field-label">Event Positions:</span>
                  <span className="review-field-val tabular-nums">
                    {trakeSlots.length} of {trakeEvents.length} events ({trakeSlots.filter((s) => s.locked).length} locked)
                  </span>
                </div>
                {isFixture && (
                  <div className="review-notice-banner">
                    <WarningIcon size={13} />
                    <span>Fixture Mode: Aligned sequences can be reviewed in workstation preview.</span>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="evidence-task-review-card" data-testid="evidence-kis-review">
              <div className="review-card-header">
                <div className="review-title-group">
                  <CheckIcon size={16} className="text-cyan" />
                  <span className="review-title">KIS Visual Search Status</span>
                </div>
              </div>
              <div className="review-card-body">
                <div className="review-field-row">
                  <span className="review-field-label">Active Query:</span>
                  <span className="review-field-val text-primary">{queryText || 'No query text'}</span>
                </div>
                {activeCandidate ? (
                  <div className="review-field-row">
                    <span className="review-field-label">Selected Candidate:</span>
                    <span className="review-field-val text-cyan tabular-nums">
                      {activeCandidate.video_id} · Frame {activeCandidate.frame_id}
                    </span>
                  </div>
                ) : (
                  <div className="review-field-row">
                    <span className="review-field-label">Selection:</span>
                    <span className="review-field-val text-muted">No candidate currently selected</span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Right Column: Submission Basket & Packaging Validator */}
        <div className="evidence-review-right-col">
          <div className="submission-basket-card" data-testid="submission-basket-card">
            <div className="basket-card-header">
              <div className="basket-title-group">
                <BasketIcon size={16} className="text-cyan" />
                <span className="basket-title">Submission Basket</span>
              </div>
              <span className="basket-count-badge tabular-nums" data-testid="basket-count-badge">
                {submissionBasket.length} / 100 predictions
              </span>
            </div>

            <div className="basket-card-body">
              {isFixture && (
                <div className="basket-fixture-alert" data-testid="basket-fixture-alert">
                  <WarningIcon size={13} />
                  <span>
                    Fixture Preview Mode Active — Items are non-submitting demo fixtures.
                  </span>
                </div>
              )}

              {submissionBasket.length === 0 ? (
                <div className="basket-empty-state" data-testid="basket-empty-state">
                  <div className="basket-empty-icon-box">
                    <BasketIcon size={24} className="empty-basket-icon" />
                  </div>
                  <p className="empty-state-title">Submission basket is empty</p>
                  <p className="empty-state-text">
                    Approved VQA answers, aligned TRAKE sequences, or verified KIS selections will appear here.
                  </p>
                </div>
              ) : (
                <div className="basket-items-list" data-testid="basket-items-list">
                  {submissionBasket.map((item, idx) => (
                    <div
                      key={`${item.video_id}-${item.frame_id}-${idx}`}
                      className="basket-item-row"
                      data-testid={`basket-item-${idx}`}
                    >
                      <div className="basket-item-info">
                        <div className="basket-item-id-row">
                          <span className="item-task-badge">{item.task || 'KIS'}</span>
                          <span className="item-vid text-cyan">{item.video_id}</span>
                          <span className="item-fid tabular-nums">
                            {item.task === 'TRAKE' && item.frame_ids
                              ? `${item.frame_ids.length} Events`
                              : `Frame ${item.frame_id}`}
                          </span>
                        </div>
                        {item.task === 'VQA' && item.answer && (
                          <div className="basket-item-answer" data-testid={`basket-answer-${idx}`}>
                            <span className="answer-prefix">Ans:</span>
                            <span className="answer-text">"{item.answer}"</span>
                          </div>
                        )}
                        {item.task === 'TRAKE' && item.frame_ids && (
                          <div className="basket-item-trake-chain" data-testid={`basket-trake-chain-${idx}`}>
                            <span className="chain-prefix">Frames:</span>
                            <span className="chain-sequence tabular-nums">
                              {item.frame_ids.join(' → ')}
                            </span>
                          </div>
                        )}
                        <div className="basket-item-meta tabular-nums">
                          {item.timestamp_ms !== undefined && (
                            <span>{(item.timestamp_ms / 1000).toFixed(1)}s · </span>
                          )}
                          <span>Added {new Date(item.added_at_utc).toLocaleTimeString()}</span>
                        </div>
                      </div>

                      <button
                        type="button"
                        className="btn-remove-basket-item"
                        onClick={() => handleRemoveFromBasket(item.video_id, item.frame_id)}
                        title="Remove from submission basket"
                        aria-label={`Remove ${item.video_id} frame ${item.frame_id}`}
                        data-testid={`btn-remove-basket-${idx}`}
                      >
                        <ClearIcon size={13} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {submissionBasket.length > 0 && (
              <div className="basket-card-footer">
                <div className="basket-summary-status">
                  <CheckIcon size={14} className="text-cyan" />
                  <span className="summary-text tabular-nums">
                    {submissionBasket.length} total prediction{submissionBasket.length > 1 ? 's' : ''} in basket ({kisItems.length} KIS, {vqaItems.length} Q&A, {trakeItems.length} TRAKE)
                  </span>
                </div>
                <div className="basket-export-actions" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '8px', marginTop: '12px' }}>
                  {/* Primary Export Button for Active Task Mode */}
                  <button
                    type="button"
                    className="btn-export-csv"
                    onClick={() => handleExportTaskCsv(taskMode)}
                    disabled={currentTaskItems.length === 0}
                    data-testid="btn-export-csv"
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '6px',
                      padding: '7px 14px',
                      background: currentTaskItems.length > 0 ? 'var(--color-cyan, #00e5ff)' : 'rgba(255, 255, 255, 0.08)',
                      color: currentTaskItems.length > 0 ? '#0a0e17' : '#64748b',
                      border: 'none',
                      borderRadius: '6px',
                      fontWeight: 600,
                      cursor: currentTaskItems.length > 0 ? 'pointer' : 'not-allowed',
                      fontSize: '12px',
                      transition: 'all 0.15s ease',
                    }}
                  >
                    <ExportIcon size={14} color={currentTaskItems.length > 0 ? '#0a0e17' : '#64748b'} />
                    <span>Export {currentTaskLabel} CSV ({currentTaskItems.length})</span>
                  </button>

                  {/* Secondary Export Buttons for other tasks present in basket */}
                  {taskMode !== 'KIS' && kisItems.length > 0 && (
                    <button
                      type="button"
                      onClick={() => handleExportTaskCsv('KIS')}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '5px',
                        padding: '6px 10px',
                        background: 'rgba(0, 229, 255, 0.1)',
                        color: '#00e5ff',
                        border: '1px solid rgba(0, 229, 255, 0.3)',
                        borderRadius: '6px',
                        cursor: 'pointer',
                        fontSize: '11.5px',
                        fontWeight: 500,
                      }}
                    >
                      <ExportIcon size={13} color="#00e5ff" />
                      <span>Export KIS ({kisItems.length})</span>
                    </button>
                  )}

                  {taskMode !== 'VQA' && vqaItems.length > 0 && (
                    <button
                      type="button"
                      onClick={() => handleExportTaskCsv('VQA')}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '5px',
                        padding: '6px 10px',
                        background: 'rgba(0, 229, 255, 0.1)',
                        color: '#00e5ff',
                        border: '1px solid rgba(0, 229, 255, 0.3)',
                        borderRadius: '6px',
                        cursor: 'pointer',
                        fontSize: '11.5px',
                        fontWeight: 500,
                      }}
                    >
                      <ExportIcon size={13} color="#00e5ff" />
                      <span>Export Q&A ({vqaItems.length})</span>
                    </button>
                  )}

                  {taskMode !== 'TRAKE' && trakeItems.length > 0 && (
                    <button
                      type="button"
                      onClick={() => handleExportTaskCsv('TRAKE')}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '5px',
                        padding: '6px 10px',
                        background: 'rgba(0, 229, 255, 0.1)',
                        color: '#00e5ff',
                        border: '1px solid rgba(0, 229, 255, 0.3)',
                        borderRadius: '6px',
                        cursor: 'pointer',
                        fontSize: '11.5px',
                        fontWeight: 500,
                      }}
                    >
                      <ExportIcon size={13} color="#00e5ff" />
                      <span>Export TRAKE ({trakeItems.length})</span>
                    </button>
                  )}

                  <button
                    type="button"
                    className="btn-clear-basket"
                    onClick={handleClearBasket}
                    data-testid="btn-clear-basket"
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '4px',
                      padding: '6px 10px',
                      background: 'rgba(255, 75, 75, 0.12)',
                      color: '#ff4b4b',
                      border: '1px solid rgba(255, 75, 75, 0.3)',
                      borderRadius: '6px',
                      cursor: 'pointer',
                      fontSize: '11.5px',
                      marginLeft: 'auto',
                    }}
                  >
                    <ClearIcon size={12} color="#ff4b4b" />
                    <span>Clear All</span>
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 3. Bottom Supporting Row: Multimodal Evidence Pack Inspector (Only rendered in VQA mode when evidence is available) */}
      {taskMode === 'VQA' && activeEvidence && (
        <div className="evidence-bottom-supporting-row">
          <EvidenceInspector evidence={activeEvidence} />
        </div>
      )}
    </div>
  )
}
