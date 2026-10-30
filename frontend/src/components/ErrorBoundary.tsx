import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Result, Button, Collapse, Typography } from 'antd'
import { ReloadOutlined, HomeOutlined } from '@ant-design/icons'

const { Text } = Typography

/**
 * Keep one broken page from taking the whole application with it.
 *
 * React 18 unmounts the **entire tree** on an uncaught render error. Without
 * a boundary, any such error produces a
 * blank white page — no message, no navigation, nothing to report to support
 * beyond "it's white".
 *
 * That is not a theoretical risk. The threat catalogue behind /lagebild is
 * bind-mounted and **meant to be edited live** by the authority, and the page
 * once read it structurally without guards: one category missing its `source`
 * would take the whole product dark for every user of that tenant. The catalogue is
 * validated now (see `Lagebild.tsx`), but validation only covers the mistake
 * we thought of. A boundary covers the ones we did not.
 *
 * Placed around the routed content inside each layout rather than at the
 * root, on purpose: the navigation, the language switch and the sign-out
 * button stay usable, so the investigator can leave the broken page instead
 * of restarting the browser.
 *
 * Deliberately not wired to a reporting service. Sending stack traces off a
 * law-enforcement workstation to a third party is a decision for the
 * deploying organisation, not a default.
 */
interface Props {
  children: ReactNode
  /** Changes to this value reset the boundary — used to clear on navigation. */
  resetKey?: string
}

interface State {
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // The browser console is the only sink. See the note above on reporting.
    console.error('[ui] render failed:', error, info.componentStack)
  }

  componentDidUpdate(prev: Props) {
    // Navigating away from the broken page must clear the error, or the user
    // is stuck on the failure screen for the rest of the session.
    if (this.state.error && prev.resetKey !== this.props.resetKey) {
      this.setState({ error: null })
    }
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    // i18n is not used here. If the failure happened while the translation
    // bundle was loading, `t()` would render raw keys — an error screen that
    // is itself broken is worse than an English one.
    return (
      <Result
        status="warning"
        title="This page could not be displayed"
        subTitle={
          'Something in this view failed to render. The rest of the '
          + 'application still works — use the navigation to continue, or '
          + 'reload to try again.'
        }
        extra={[
          <Button type="primary" key="reload" icon={<ReloadOutlined />}
                  onClick={() => window.location.reload()}>
            Reload
          </Button>,
          <Button key="home" icon={<HomeOutlined />}
                  onClick={() => { window.location.href = '/' }}>
            Back to start
          </Button>,
        ]}
      >
        <Collapse
          size="small"
          ghost
          items={[{
            key: 'detail',
            label: <Text type="secondary" style={{ fontSize: 12 }}>
              Technical details
            </Text>,
            children: (
              <Text code style={{ fontSize: 11, wordBreak: 'break-all' }}>
                {error.message || String(error)}
              </Text>
            ),
          }]}
        />
      </Result>
    )
  }
}
