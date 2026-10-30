import { useState } from 'react'
import { useLocation } from 'react-router-dom'
import { Typography, Alert } from 'antd'
import { useTranslation } from 'react-i18next'
import SearchForm from '../components/search/SearchForm'

interface Props {
  /** Rendered at /news: the ordinary search, with the news module
   *  preselected. The analyst types the term; everything else — facets,
   *  case assignment, progress — is the same form as always. */
  newsPreset?: boolean
}

export default function Search({ newsPreset }: Props) {
  const { t } = useTranslation()
  const location = useLocation()
  // The Lagebild page navigates here with a prefilled topic. Held in state
  // so it is applied once and then cleared — otherwise a re-render would
  // keep resetting whatever the analyst has since typed.
  const [prefill, setPrefill] = useState(
    (location.state as any)?.prefill
    || (newsPreset ? { type: 'keyword', modules: ['news'] } : null),
  )

  return (
    <div style={{ maxWidth: 720 }}>
      <Typography.Title level={3}>
        {newsPreset ? t('news.title') : t('search.title')}
      </Typography.Title>
      {newsPreset && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={t('news.intro')}
          description={t('news.hint')}
        />
      )}
      <SearchForm
        redirectAfterSubmit
        prefill={prefill}
        onPrefillConsumed={() => setPrefill(null)}
      />
    </div>
  )
}
