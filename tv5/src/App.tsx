import React, { useEffect } from 'react'
import { ProductHeader } from './components/ProductHeader'
import { RetrievalWorkspace } from './components/RetrievalWorkspace'
import { InspectionWorkspace } from './components/InspectionWorkspace'
import { EvidenceSubmissionWorkspace } from './components/EvidenceSubmissionWorkspace'
import { EvaluationWorkspace } from './components/EvaluationWorkspace'
import { KeyboardHelpModal } from './components/KeyboardHelpModal'
import { useAppDispatch, useAppState } from './state/AppContext'
import { fetchHealth } from './api/tv4Client'
import { useExactInspectionCoordinator } from './state/useExactInspectionCoordinator'

export const App: React.FC = () => {
  const dispatch = useAppDispatch()
  const { activeTab, isKeyboardHelpOpen } = useAppState()

  // Single authoritative owner for exact-neighbor & exact-frame lifecycle
  useExactInspectionCoordinator()

  useEffect(() => {
    let isMounted = true
    fetchHealth()
      .then((health) => {
        if (isMounted) {
          dispatch({ type: 'SET_HEALTH', payload: { health } })
        }
      })
      .catch((err) => {
        if (isMounted) {
          dispatch({
            type: 'SET_HEALTH',
            payload: { health: null, error: err.message || 'Service unavailable' },
          })
        }
      })

    return () => {
      isMounted = false
    }
  }, [dispatch])

  // Global focus-safe keyboard listener for '?' help modal toggle
  useEffect(() => {
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement
      const isInput =
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.tagName === 'SELECT' ||
          target.isContentEditable)

      if (e.key === '?' || (e.shiftKey && e.key === '/')) {
        if (!isInput) {
          e.preventDefault()
          dispatch({ type: 'TOGGLE_KEYBOARD_HELP' })
        }
      } else if (e.key === 'Escape' && isKeyboardHelpOpen) {
        e.preventDefault()
        dispatch({ type: 'SET_KEYBOARD_HELP', payload: false })
      }
    }

    window.addEventListener('keydown', handleGlobalKeyDown)
    return () => {
      window.removeEventListener('keydown', handleGlobalKeyDown)
    }
  }, [dispatch, isKeyboardHelpOpen])

  return (
    <div className="multimodal-workstation">
      <ProductHeader />
      <div className="workspace-tab-viewport">
        {activeTab === 'retrieval' && <RetrievalWorkspace />}
        {activeTab === 'inspection' && <InspectionWorkspace />}
        {activeTab === 'evidence' && <EvidenceSubmissionWorkspace />}
        {activeTab === 'evaluation' && <EvaluationWorkspace />}
      </div>
      <KeyboardHelpModal
        isOpen={isKeyboardHelpOpen}
        onClose={() => dispatch({ type: 'SET_KEYBOARD_HELP', payload: false })}
      />
    </div>
  )
}
