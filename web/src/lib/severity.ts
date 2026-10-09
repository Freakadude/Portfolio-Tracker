/** How severities look across Insights: the badge tone and the stripe down the left of a card,
 * so the loudest items can be told apart from far away. */
export const TONE = {
  critical: 'bad',
  high: 'bad',
  medium: 'warn',
  low: 'neutral',
  info: 'neutral',
} as const

export const STRIPE = {
  critical: 'border-l-danger',
  high: 'border-l-danger',
  medium: 'border-l-amber-500',
  low: 'border-l-primary/40',
  info: 'border-l-border',
} as const

export const stripeOf = (severity: string) => STRIPE[severity as keyof typeof STRIPE] ?? STRIPE.info
export const toneOf = (severity: string) => TONE[severity as keyof typeof TONE] ?? 'neutral'
