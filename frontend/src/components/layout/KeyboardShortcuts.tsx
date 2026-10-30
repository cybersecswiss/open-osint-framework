import { useEffect, useState } from 'react'
import { Modal, Table, Tag, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

const { Text, Paragraph } = Typography

/**
 * A keyboard layer for people who live in this app all day.
 *
 * ## Shape
 *
 * `g` then a letter navigates — the two-key "go to" idiom from Gmail and
 * GitHub, chosen over single letters on purpose: a single-letter shortcut
 * fires the moment a stray keystroke lands outside a field, and in a tool
 * where a keystroke can start a search that is the wrong trade. `?` opens
 * this list, because a shortcut nobody can discover is a shortcut nobody
 * uses.
 *
 * ## The guard that matters
 *
 * **Nothing fires while focus is in a field.** Typing "Crimson Wolves" into
 * the search box must not navigate on the `g`. The check covers `input`,
 * `textarea`, `select`, anything `contenteditable`, and any element inside
 * an open AntD dropdown or modal — plus every combination with a modifier,
 * so Ctrl+G (the browser's own find-again) is never swallowed.
 *
 * This is the difference between a shortcut layer and a trap.
 */
const ROUTES: Record<string, string> = {
  d: '/',
  c: '/cases',
  s: '/search',
  l: '/lagebild',
  n: '/news',
  m: '/monitoring',
  h: '/handbook',
}

function isTyping(el: Element | null): boolean {
  if (!el || !(el instanceof HTMLElement)) return false
  const tag = el.tagName.toLowerCase()
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return true
  if (el.isContentEditable) return true
  // AntD renders comboboxes and rich pickers as divs with a role; typing
  // inside those must be just as safe as inside a bare <input>.
  const role = el.getAttribute('role')
  if (role && ['combobox', 'textbox', 'searchbox', 'listbox'].includes(role)) return true
  return !!el.closest('.ant-select, .ant-picker, .ant-modal, [contenteditable="true"]')
}

export default function KeyboardShortcuts() {
  const navigate = useNavigate()
  const { t } = useTranslation()
  const [helpOpen, setHelpOpen] = useState(false)

  useEffect(() => {
    let pendingG = 0

    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return
      if (isTyping(document.activeElement)) return

      if (e.key === '?') {
        e.preventDefault()
        setHelpOpen(true)
        return
      }
      if (e.key === 'g' || e.key === 'G') {
        pendingG = Date.now()
        return
      }
      // The 1.5 s window keeps a `g` typed minutes ago from turning an
      // unrelated `c` into a navigation.
      if (pendingG && Date.now() - pendingG < 1500) {
        const target = ROUTES[e.key.toLowerCase()]
        pendingG = 0
        if (target) {
          e.preventDefault()
          navigate(target)
        }
      }
    }

    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [navigate])

  const rows = [
    { keys: ['?'], what: t('shortcuts.help') },
    ...Object.entries(ROUTES).map(([k, path]) => ({
      keys: ['g', k], what: t(`shortcuts.go_${k}`), path,
    })),
  ]

  return (
    <Modal open={helpOpen} onCancel={() => setHelpOpen(false)} footer={null}
           title={t('shortcuts.title')} width={520}>
      <Paragraph type="secondary">{t('shortcuts.intro')}</Paragraph>
      <Table
        rowKey={(r: any) => r.keys.join('-')}
        size="small" pagination={false} dataSource={rows}
        columns={[
          { title: t('shortcuts.col_keys'), width: 120,
            render: (_: any, r: any) => (
              <span>{r.keys.map((k: string, i: number) => (
                <Tag key={i} style={{ fontFamily: 'monospace' }}>{k}</Tag>
              ))}</span>
            ) },
          { title: t('shortcuts.col_action'),
            render: (_: any, r: any) => <Text>{r.what}</Text> },
        ]}
      />
    </Modal>
  )
}
