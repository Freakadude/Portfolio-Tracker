import {
  ProjectionChart,
  type ProjectionAssumptions,
  type ProjectionRow,
} from '../../reports/ProjectionChart'
import type { WidgetProps } from '../types'

export interface ProjectionData {
  empty?: boolean
  reason?: string
  assumptions?: ProjectionAssumptions
  points?: ProjectionRow[]
}

/** The projection on a dashboard (FR-PF-12): the assumptions are on the chart. */
export function ProjectionWidget({ data }: WidgetProps<ProjectionData>) {
  if (data.empty || !data.assumptions || !data.points)
    return <p className="text-sm text-muted">{data.reason}</p>
  return <ProjectionChart rows={data.points} assumptions={data.assumptions} />
}
