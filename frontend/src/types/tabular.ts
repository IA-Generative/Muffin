// The profile of a tabular file (#431), as GET /api/collections/{c}/documents/{d}/tabular-profile gives it.

// What the analysis found in a column - the shape of its source (docs/analyse-json.md of spreadsheet-analyser).
export interface TabularColumn {
  index: number
  name: string
  type: string // integer | number | text | boolean | date | datetime | time | mixed | empty | error
  non_null: number
  null: number
  distinct: number
  // False once more distinct values were seen than the analysis counts: `distinct` is then a lower bound.
  distinct_exact: boolean
  sample_values: unknown[]
  error_cells?: number
  numeric?: {
    count: number
    min: number | null
    max: number | null
    sum: number | null
    mean: number | null
    std: number | null
    median: number | null
  }
  text?: { min_length: number; max_length: number; avg_length: number | null }
  dates?: { min: string; max: string }
  top_values?: { value: string; count: number }[]
}

export interface TabularSheet {
  index: number
  name: string
  hidden: boolean
  rows: number
  header_detected: boolean
  truncated: boolean
  columns: TabularColumn[]
  preview: unknown[][]
  warnings: string[]
  // The typed copy that SQL reads: the SQL type of each column. Null for a sheet with nothing to copy.
  table: { rows: number; columns: { name: string; sql_type: string }[] } | null
}

// A column of the profile of the document (the main sheet) - the shape Muffin has always had.
export interface LegacyColumn {
  name: string
  type: string
  semantic_type: string
  null_count: number
  distinct_count: number
  top_values?: { value: unknown; count: number }[]
  numeric_stats?: { min: number | null; max: number | null; mean: number | null; median: number | null } | null
  date_stats?: { min: string | null; max: string | null } | null
  text_stats?: { min_length: number; max_length: number; avg_length: number | null } | null
}

export interface TabularProfile {
  row_count: number
  column_count: number
  format: string
  columns: LegacyColumn[]
  sample_rows: Record<string, unknown>[]
  measures: string[]
  dimensions: string[]
  text_columns: string[]
  // null: a profile from before the sheets were kept; it has none until the document is indexed again.
  analysis_version: number | null
  sheets: TabularSheet[]
}
