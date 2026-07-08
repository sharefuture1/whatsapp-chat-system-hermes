import { useSettings } from '../settings'
import { fmtTime } from '../format'

export default function MemorySummary({ detail }) {
  const { t } = useSettings()
  return (
    <div className="memory-panel">
      <div className="memory-meta-grid">
        <div className="memory-meta-card">
          <span className="subtle">{t('priority')}</span>
          <strong>{detail?.profile_summary?.priority || 'normal'}</strong>
        </div>
        <div className="memory-meta-card">
          <span className="subtle">{t('languageHint')}</span>
          <strong>{detail?.profile_summary?.language_hint || 'Unknown'}</strong>
        </div>
        <div className="memory-meta-card">
          <span className="subtle">{t('sessions')}</span>
          <strong>{detail?.session_ids?.length || 0}</strong>
        </div>
      </div>
      <div className="memory-box">
        <h3>{t('memoryTitle')}</h3>
        <pre>{detail?.memory_markdown || t('noMemory')}</pre>
      </div>
    </div>
  )
}
