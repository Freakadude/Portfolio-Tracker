import { Fragment, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Badge } from '../../components/display'
import type { WidgetProps } from '../types'

/** Bold and italic inside one line. Everything is plain text: no HTML is ever inserted. */
function inline(text: string): ReactNode[] {
  const out: ReactNode[] = []
  const pattern = /(\*\*[^*]+\*\*|\*[^*]+\*)/g
  let last = 0
  for (const match of text.matchAll(pattern)) {
    const at = match.index ?? 0
    if (at > last) out.push(text.slice(last, at))
    const token = match[0]
    out.push(
      token.startsWith('**') ? (
        <strong key={at}>{token.slice(2, -2)}</strong>
      ) : (
        <em key={at}>{token.slice(1, -1)}</em>
      ),
    )
    last = at + token.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

/** A small Markdown subset: headings, bullet lists, bold, italic and paragraphs. */
export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = []
  let list: string[] = []
  const flush = () => {
    if (list.length === 0) return
    blocks.push(
      <ul key={`ul${blocks.length}`} className="list-disc space-y-0.5 pl-5">
        {list.map((item, i) => (
          <li key={i}>{inline(item)}</li>
        ))}
      </ul>,
    )
    list = []
  }
  text.split('\n').forEach((raw, n) => {
    const line = raw.trimEnd()
    const bullet = line.match(/^\s*[-*]\s+(.*)$/)
    if (bullet) {
      list.push(bullet[1])
      return
    }
    flush()
    const heading = line.match(/^(#{1,3})\s+(.*)$/)
    if (heading) {
      blocks.push(
        <p key={n} className={heading[1].length === 1 ? 'text-lg font-semibold' : 'font-semibold'}>
          {inline(heading[2])}
        </p>,
      )
    } else if (line.trim()) {
      blocks.push(<p key={n}>{inline(line)}</p>)
    }
  })
  flush()
  return (
    <div className="space-y-1 text-sm">
      {blocks.map((b, i) => (
        <Fragment key={i}>{b}</Fragment>
      ))}
    </div>
  )
}

export function NoteWidget({ data }: WidgetProps<{ text: string }>) {
  const { t } = useTranslation()
  if (!data.text.trim()) return <p className="text-sm text-muted">{t('widgets.noteEmpty')}</p>
  return <Markdown text={data.text} />
}

/** A widget whose data arrives in a later phase says which, instead of showing nothing. */
export function UnavailableWidget({ data }: WidgetProps<{ reason?: string }>) {
  const { t } = useTranslation()
  return (
    <div className="space-y-2">
      <Badge tone="warn">{t('widgets.comingLater')}</Badge>
      <p className="text-sm text-muted">{data.reason}</p>
    </div>
  )
}
