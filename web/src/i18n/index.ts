import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './en.json'
import agent from './en.agent.json'
import dashboards from './en.dashboards.json'
import lookthrough from './en.lookthrough.json'
import news from './en.news.json'
import notify from './en.notify.json'
import schedules from './en.schedules.json'
import sleeves from './en.sleeves.json'
import strategies from './en.strategies.json'
import tools from './en.tools.json'
import watchlist from './en.watchlist.json'
import whatIf from './en.whatif.json'
import holdings from './en.holdings.json'
import overview from './en.overview.json'
import transactions from './en.transactions.json'

// English only for now; add another set of bundles here and a language switch to ship Dutch.
// Strings live in one file per area; each file's top-level keys are merged into one namespace.
export const resources = {
  ...en,
  ...holdings,
  ...transactions,
  ...overview,
  ...dashboards,
  ...sleeves,
  ...schedules,
  ...watchlist,
  ...whatIf,
  ...tools,
  ...strategies,
  ...notify,
  ...lookthrough,
  ...news,
  ...agent,
}

void i18n.use(initReactI18next).init({
  resources: { en: { translation: resources } },
  lng: 'en',
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
})

export default i18n
