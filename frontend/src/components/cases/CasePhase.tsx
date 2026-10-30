import { Steps, Tooltip, Typography, Space } from 'antd'
import { useTranslation } from 'react-i18next'

const { Text } = Typography

/**
 * Where the investigator is in their work.
 *
 * The functions for a whole investigation were all there — search, triage,
 * pivot, open selectors, map, timeline, report — but nothing said in what
 * order, and nothing recorded where you had got to. That made the case a
 * landscape of tools instead of a piece of work with a beginning and an end.
 *
 * Three rules keep this an aid rather than a cage:
 *
 *  1. **It is set by hand, never by the system.** A phase that advances
 *     itself asserts something about the state of an investigation that only
 *     the person doing it knows, and in a case file a wrong assertion of that
 *     kind is worse than none.
 *  2. **Every step stays reachable.** Investigations are not linear — you go
 *     back to collecting because the analysis raised a question. A control
 *     that punished going back would simply be worked around.
 *  3. **It is not progress.** There is no measure of when an investigation is
 *     complete, so there is no percentage here and no "N of 4 done". The
 *     phase says what you are doing, not how far along you are.
 */

export const PHASES = ['new', 'collecting', 'analysing', 'reporting'] as const
export type Phase = typeof PHASES[number]

export default function CasePhase({
  phase, disabled, onChange,
}: {
  phase?: string
  disabled?: boolean
  onChange: (next: Phase) => void
}) {
  const { t } = useTranslation()
  const current = Math.max(0, PHASES.indexOf((phase || 'new') as Phase))

  return (
    <Space direction="vertical" size={2} style={{ width: '100%' }}>
      <Steps
        size="small"
        type="navigation"
        current={current}
        onChange={disabled ? undefined : (i) => onChange(PHASES[i])}
        style={{ marginBottom: 0 }}
        items={PHASES.map((p) => ({
          title: t(`case_phase.${p}`),
          description: (
            <Tooltip title={t(`case_phase.${p}_hint`)}>
              <Text type="secondary" style={{ fontSize: 11 }}>
                {t(`case_phase.${p}_short`)}
              </Text>
            </Tooltip>
          ),
        }))}
      />
      <Text type="secondary" style={{ fontSize: 11 }}>
        {t('case_phase.note')}
      </Text>
    </Space>
  )
}
