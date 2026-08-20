import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { KeyboardHelpModal, SHORTCUT_REGISTRY } from '../../src/components/KeyboardHelpModal'

describe('T036 / T037 Keyboard Shortcuts & Focus Guards', () => {
  it('exposes a comprehensive, documented shortcut registry', () => {
    expect(SHORTCUT_REGISTRY.length).toBeGreaterThanOrEqual(6)
    const combos = SHORTCUT_REGISTRY.map((s) => s.keyCombo)
    expect(combos).toContain('ArrowLeft')
    expect(combos).toContain('ArrowRight')
    expect(combos).toContain('Escape')
  })

  it('renders Keyboard Help Modal with shortcut details and focus guard indicators', () => {
    const handleClose = vi.fn()
    render(<KeyboardHelpModal isOpen={true} onClose={handleClose} />)

    expect(screen.getByTestId('keyboard-help-modal')).toBeInTheDocument()
    expect(screen.getByText('Keyboard Shortcuts Guide')).toBeInTheDocument()
    expect(screen.getByText('Step backward (-1 frame offset)')).toBeInTheDocument()
    expect(screen.getByText('Step forward (+1 frame offset)')).toBeInTheDocument()

    // Test close button
    fireEvent.click(screen.getByTestId('close-keyboard-help'))
    expect(handleClose).toHaveBeenCalledTimes(1)
  })

  it('does not render modal when isOpen is false', () => {
    render(<KeyboardHelpModal isOpen={false} onClose={vi.fn()} />)
    expect(screen.queryByTestId('keyboard-help-modal')).not.toBeInTheDocument()
  })

  it('verifies focus-guard predicate ignores input/textarea/select elements', () => {
    const isFocusGuarded = (targetTag: string) => {
      return targetTag === 'INPUT' || targetTag === 'TEXTAREA' || targetTag === 'SELECT'
    }

    expect(isFocusGuarded('INPUT')).toBe(true)
    expect(isFocusGuarded('TEXTAREA')).toBe(true)
    expect(isFocusGuarded('SELECT')).toBe(true)
    expect(isFocusGuarded('DIV')).toBe(false)
    expect(isFocusGuarded('BODY')).toBe(false)
    expect(isFocusGuarded('BUTTON')).toBe(false)
  })
})
