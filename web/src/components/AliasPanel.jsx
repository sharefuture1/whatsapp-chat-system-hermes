export default function AliasPanel({ aliases }) {
  return (
    <section className="panel luxury-panel">
      <div className="panel-header tight">
        <div>
          <h2>Alias Directory</h2>
          <div className="subtle">Fast numeric shortcuts for operator workflows.</div>
        </div>
      </div>
      <div className="alias-list professional">
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
