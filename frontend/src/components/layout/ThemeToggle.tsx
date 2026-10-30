import { Segmented, Tooltip } from 'antd'
import { SunOutlined, MoonOutlined, DesktopOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { useStore, type ThemeMode } from '../../store/useStore'

/**
 * Light / dark / follow-the-system.
 *
 * Three states rather than a two-way switch, and the default is `system`.
 * A binary toggle has to pick a side for a user who never expressed one, and
 * on a workstation the operating system already knows the answer — often set
 * centrally by the IT department. Following it is the choice that respects a
 * decision already made, and the two explicit options are there for the
 * shift where the room lighting disagrees with the policy.
 */
export default function ThemeToggle({ dark = false }: { dark?: boolean }) {
  const { t } = useTranslation()
  const mode = useStore((s) => s.themeMode)
  const setMode = useStore((s) => s.setThemeMode)

  return (
    <Tooltip title={t('theme.tooltip')}>
      <Segmented
        size="small"
        value={mode}
        onChange={(v) => setMode(v as ThemeMode)}
        aria-label={t('theme.tooltip')}
        style={dark ? { background: 'rgba(255,255,255,0.12)' } : undefined}
        options={[
          { value: 'light', icon: <SunOutlined aria-label={t('theme.light')} />,
            title: t('theme.light') },
          { value: 'system', icon: <DesktopOutlined aria-label={t('theme.system')} />,
            title: t('theme.system') },
          { value: 'dark', icon: <MoonOutlined aria-label={t('theme.dark')} />,
            title: t('theme.dark') },
        ]}
      />
    </Tooltip>
  )
}
