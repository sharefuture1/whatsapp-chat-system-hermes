const VIEWPORT_HEIGHT_PROPERTY = '--app-viewport-height'

export function readViewportHeight(view) {
  const visualHeight = Number(view?.visualViewport?.height)
  if (Number.isFinite(visualHeight) && visualHeight > 0) return Math.round(visualHeight)

  const innerHeight = Number(view?.innerHeight)
  return Number.isFinite(innerHeight) && innerHeight > 0 ? Math.round(innerHeight) : null
}
export function installViewportHeightSync(
  view = globalThis.window,
  root = globalThis.document?.documentElement,
) {
  if (!view || !root?.style?.setProperty) return () => {}

  const visualViewport = view.visualViewport
  const update = () => {
    const height = readViewportHeight(view)
    if (height) root.style.setProperty(VIEWPORT_HEIGHT_PROPERTY, `${height}px`)
  }

  update()
  view.addEventListener?.('resize', update)
  visualViewport?.addEventListener?.('resize', update)
  visualViewport?.addEventListener?.('scroll', update)

  return () => {
    view.removeEventListener?.('resize', update)
    visualViewport?.removeEventListener?.('resize', update)
    visualViewport?.removeEventListener?.('scroll', update)
  }
}
