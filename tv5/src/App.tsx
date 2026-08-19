import React, { useEffect } from 'react'
import { ProductHeader } from './components/ProductHeader'
import { RetrievalWorkspace } from './components/RetrievalWorkspace'
import { InspectionWorkspace } from './components/InspectionWorkspace'
import { EvidenceSubmissionWorkspace } from './components/EvidenceSubmissionWorkspace'
import { useAppDispatch, useAppState } from './state/AppContext'
import { fetchHealth } from './api/tv4Client'
import { useExactInspectionCoordinator } from './state/useExactInspectionCoordinator'

export const App: React.FC = () => {
  const dispatch = useAppDispatch()
  const { activeTab } = useAppState()

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

  return (
    <div className="multimodal-workstation">
      <ProductHeader />
      <div className="workspace-tab-viewport">
        {activeTab === 'retrieval' && <RetrievalWorkspace />}
        {activeTab === 'inspection' && <InspectionWorkspace />}
        {activeTab === 'evidence' && <EvidenceSubmissionWorkspace />}
      </div>
    </div>
  )
}
