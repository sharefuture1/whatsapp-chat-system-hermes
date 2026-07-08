import { useSettings } from '../settings'

export default function AliasPanel({ aliases, onOpenSettings }) {
  const { t } = useSettings()
  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <h2>{t('aliasDirectory')}</h2>
          <div className="subtle">{t('hintAlias')}</div>
        </div>
        <button className="ghost-btn small-btn" onClick={onOpenSettings}>{t('settings')}</button>
      </div>
      <div className="alias-list">
        {aliases.length === 0 ? <div className="empty-state subtle">{t('noAliases')}</div> : null}
        {aliases.map(([alias, info]) => (
          <div key={alias} className="alias-item">
            <div><strong>{alias}</strong> · {info.name}</div>
            <div className="subtle">{info.chat_id}</div>
          </div>
        ))}
      </div>
    </section>
  )
}
