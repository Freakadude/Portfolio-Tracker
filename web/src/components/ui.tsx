import { forwardRef, useId, type ReactNode } from 'react'
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from 'react'
import { cn } from '../lib/cn'

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost'
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant = 'primary', type = 'button', ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        'inline-flex min-h-10 items-center justify-center rounded-md px-4 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50',
        variant === 'primary' && 'bg-primary text-primary-foreground hover:opacity-90',
        variant === 'secondary' && 'border border-border bg-card hover:bg-border/40',
        variant === 'ghost' && 'hover:bg-border/40',
        className,
      )}
      {...props}
    />
  )
})

const control =
  'min-h-10 w-full rounded-md border border-border bg-card px-3 text-sm text-foreground placeholder:text-muted disabled:opacity-50'

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...props }, ref) {
    return <input ref={ref} className={cn(control, className)} {...props} />
  },
)

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className, ...props }, ref) {
    return <select ref={ref} className={cn(control, className)} {...props} />
  },
)

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, ...props }, ref) {
  return <textarea ref={ref} className={cn(control, 'py-2 font-mono', className)} {...props} />
})

/** Label + control + error, wired together for screen readers. */
export function Field({
  label,
  error,
  hint,
  children,
}: {
  label: string
  error?: string
  hint?: string
  children: (props: {
    id: string
    'aria-describedby'?: string
    'aria-invalid'?: boolean
  }) => ReactNode
}) {
  const id = useId()
  const describedBy = error ? `${id}-err` : hint ? `${id}-hint` : undefined
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
      </label>
      {children({ id, 'aria-describedby': describedBy, 'aria-invalid': error ? true : undefined })}
      {error ? (
        <p id={`${id}-err`} role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-sm text-muted">
          {hint}
        </p>
      ) : null}
    </div>
  )
}

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('rounded-lg border border-border bg-card p-6', className)} {...props} />
}

/** A closed-by-default "What is this?" note: what a screen is for and how to use it, kept out of
 * the way once the owner knows. */
export function Help({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className="rounded-md border border-border bg-card px-3 py-2 text-sm">
      <summary className="cursor-pointer font-medium">{title}</summary>
      <div className="mt-2 space-y-2 text-muted">{children}</div>
    </details>
  )
}

export function Alert({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="rounded-md border border-danger/50 px-3 py-2 text-sm text-danger">
      {children}
    </p>
  )
}

export function Checkbox({
  label,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return (
    <label className="flex min-h-10 items-center gap-2 text-sm">
      <input type="checkbox" className="size-4 accent-[var(--primary)]" {...props} />
      {label}
    </label>
  )
}
