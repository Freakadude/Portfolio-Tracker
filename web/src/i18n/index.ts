import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './en.json'
import holdings from './en.holdings.json'
import transactions from './en.transactions.json'

// English only for now; add another set of bundles here and a language switch to ship Dutch.
// Strings live in one file per area; each file's top-level keys are merged into one namespace.
export const resources = { ...en, ...holdings, ...transactions }

void i18n.use(initReactI18next).init({
  resources: { en: { translation: resources } },
  lng: 'en',
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
})

export default i18n
