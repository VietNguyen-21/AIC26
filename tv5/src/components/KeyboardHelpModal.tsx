import React from 'react'

export interface ShortcutDefinition {
  category: string
  keyCombo: string
  description: string
  focusSafe: boolean
}

export const SHORTCUT_REGISTRY: ShortcutDefinition[] = [
  { category: 'Search & Navigation', keyCombo: 'Ctrl+Enter / Cmd+Enter', description: 'Submit search query', focusSafe: false },
  { category: 'Search & Navigation', keyCombo: 'Escape', description: 'Close modals / dropdowns / reset active inspection', focusSafe: true },
  { category: 'Exact Frame Inspection', keyCombo: 'ArrowLeft', description: 'Step backward (-1 frame offset)', focusSafe: true },
  { category: 'Exact Frame Inspection', keyCombo: 'ArrowRight', description: 'Step forward (+1 frame offset)', focusSafe: true },
  { category: 'Exact Frame Inspection', keyCombo: 'Home / 0', description: 'Reset to root anchor (0 offset)', focusSafe: true },
  { category: 'Workflow & Actions', keyCombo: 'Space', description: 'Toggle video playback in media inspector', focusSafe: true },
  { category: 'Help', keyCombo: '?', description: 'Toggle Keyboard Shortcuts Guide', focusSafe: true },
]

interface KeyboardHelpModalProps {
  isOpen: boolean
  onClose: () => void
}

export const KeyboardHelpModal: React.FC<KeyboardHelpModalProps> = ({ isOpen, onClose }) => {
  if (!isOpen) return null

  return (
    <div className="modal-overlay" data-testid="keyboard-help-modal" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2 className="modal-title">Keyboard Shortcuts Guide</h2>
          <button type="button" className="close-btn" onClick={onClose} data-testid="close-keyboard-help">
            ✕
          </button>
        </div>
        <div className="modal-body">
          <p className="modal-intro">
            All operator shortcuts include focus guards: they do not trigger destructively while typing in search, answers, or text fields.
          </p>
          <div className="shortcuts-table-wrap">
            <table className="shortcuts-table">
              <thead>
                <tr>
                  <th>Category</th>
                  <th>Key Combo</th>
                  <th>Description</th>
                  <th>Focus Guarded</th>
                </tr>
              </thead>
              <tbody>
                {SHORTCUT_REGISTRY.map((s, i) => (
                  <tr key={i}>
                    <td><span className="badge-category">{s.category}</span></td>
                    <td><kbd className="key-combo">{s.keyCombo}</kbd></td>
                    <td>{s.description}</td>
                    <td>{s.focusSafe ? <span className="guard-safe">Yes (Focus Safe)</span> : <span>Contextual</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
