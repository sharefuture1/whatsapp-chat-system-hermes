import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { SUPPORTED_LANGUAGES, t as translate } from './i18n'

const SettingsCtx = createContext(null)

const LANG_KEY = 'chat-system-language-v2'
const THEME_KEY = 'chat-system-theme'

function readStored(key, fallback) {
  if (typeof localStorage === 'undefined') return fallback
  return localStorage.getItem(key) || fallback
}

export function SettingsProvider({ children }) {
  const [language, setLanguageState] = useState(() => readStored(LANG_KEY, 'zh'))
  const [theme, setThemeState] = useState(() => readStored(THEME_KEY, 'dark'))

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    document.documentElement.style.colorScheme = theme === 'light' ? 'light' : 'dark'
  }, [theme])

  useEffect(() => {
    localStorage.setItem(LANG_KEY, language)
  }, [language])

  useEffect(() => {
    localStorage.setItem(THEME_KEY, theme)
  }, [theme])

  const value = useMemo(() => ({
    language,
    theme,
    languages: SUPPORTED_LANGUAGES,
    setLanguage: (lang) => setLanguageState(SUPPORTED_LANGUAGES.some(l => l.code === lang) ? lang : 'zh'),
    setTheme: (next) => setThemeState(next === 'light' ? 'light' : 'dark'),
    toggleTheme: () => setThemeState((prev) => (prev === 'light' ? 'dark' : 'light')),
    t: (key) => translate(language, key),
  }), [language, theme])

  return <SettingsCtx.Provider value={value}>{children}</SettingsCtx.Provider>
}

export function useSettings() {
  const ctx = useContext(SettingsCtx)
  if (!ctx) {
    return {
      language: 'zh',
      theme: 'dark',
      languages: SUPPORTED_LANGUAGES,
      setLanguage: () => {},
      setTheme: () => {},
      toggleTheme: () => {},
      t: (key) => translate('zh', key),
    }
  }
  return ctx
}
