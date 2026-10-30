import { useMemo, useState } from 'react'
import { Alert, Button, Space, Typography } from 'antd'
import {
  SearchOutlined, FileTextOutlined, CheckSquareOutlined,
  AimOutlined, FilePdfOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { nextStep, isDismissed, dismiss, type NextStepKind } from '../../utils/nextStep'

const { Text } = Typography

/**
 * One suggestion for what to do next in this case, with its reason.
 *
 * The thread through the tools. Everything it says is derived from what is
 * actually in the case (see utils/nextStep.ts) — never from the phase, which
 * is the investigator's own note and must not steer what the application
 * recommends.
 *
 * It is a suggestion in the strict sense: the reason is stated so it can be
 * disagreed with, the action is one click and so is ignoring it, and closing
 * it is remembered. It does not block anything and it never claims the case
 * is complete.
 */
export default function NextStepBar({
  caseId, entities, worklist, onGoTab, onPaste, onReport,
}: {
  caseId: string
  entities?: any[] | null
  worklist?: { total?: number; candidates?: number } | null
  onGoTab: (tab: string) => void
  onPaste: () => void
  onReport: () => void
}) {
  const { t } = useTranslation()
  const [closed, setClosed] = useState<NextStepKind | null>(null)

  const step = useMemo(() => nextStep({ entities, worklist }), [entities, worklist])

  if (!step) return null
  if (closed === step.kind || isDismissed(caseId, step.kind)) return null

  const close = () => { dismiss(caseId, step.kind); setClosed(step.kind) }

  const actions: Record<NextStepKind, JSX.Element> = {
    start: (
      <Space>
        <Button size="small" type="primary" icon={<SearchOutlined />}
          onClick={() => onGoTab('search')}>
          {t('next_step.start_search')}
        </Button>
        <Button size="small" icon={<FileTextOutlined />} onClick={onPaste}>
          {t('next_step.start_paste')}
        </Button>
      </Space>
    ),
    triage: (
      <Button size="small" type="primary" icon={<CheckSquareOutlined />}
        onClick={() => onGoTab('findings')}>
        {t('next_step.go_triage')}
      </Button>
    ),
    selectors: (
      <Button size="small" type="primary" icon={<AimOutlined />}
        onClick={() => onGoTab('worklist')}>
        {t('next_step.go_selectors')}
      </Button>
    ),
    report: (
      <Button size="small" type="primary" icon={<FilePdfOutlined />}
        onClick={onReport}>
        {t('next_step.go_report')}
      </Button>
    ),
  }

  return (
    <Alert
      type={step.kind === 'report' ? 'success' : 'info'}
      showIcon
      closable
      onClose={close}
      style={{ marginBottom: 12 }}
      message={
        <Space wrap size={8}>
          <Text strong>{t(`next_step.${step.kind}_title`, { count: step.count })}</Text>
          {actions[step.kind]}
        </Space>
      }
      // The reason, always. A suggestion whose basis is hidden is an order.
      description={
        <Text type="secondary" style={{ fontSize: 12 }}>
          {t(`next_step.${step.kind}_why`, { count: step.count })}
        </Text>
      }
    />
  )
}
