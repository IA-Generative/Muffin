import type { LegacyColumn, TabularColumn, TabularProfile, TabularSheet } from '../types/tabular.ts'

const TYPE_LABEL: Record<string, string> = {
  integer: 'entier',
  number: 'nombre',
  text: 'texte',
  boolean: 'booléen',
  date: 'date',
  datetime: 'date et heure',
  time: 'heure',
  mixed: 'mixte',
  empty: 'vide',
  error: 'erreur',
}

export function typeLabel(type: string): string {
  return TYPE_LABEL[type] ?? type
}

const numberFormat = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 2 })

export function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : numberFormat.format(value)
}

export function formatCount(count: number): string {
  return numberFormat.format(count)
}

// "≥ 1 000" when the analysis stopped counting: the number is then a lower bound, not the count.
export function formatDistinct(column: Pick<TabularColumn, 'distinct' | 'distinct_exact'>): string {
  return `${column.distinct_exact ? '' : '≥ '}${formatCount(column.distinct)}`
}

// What a column holds, in a few words: the figures that tell it apart from the others.
export function columnDetails(column: TabularColumn): string[] {
  const details: string[] = []
  if (column.numeric) {
    const { min, max, mean, median } = column.numeric
    details.push(`min ${formatNumber(min)} · max ${formatNumber(max)}`)
    details.push(`moyenne ${formatNumber(mean)} · médiane ${formatNumber(median)}`)
  }
  if (column.dates) details.push(`du ${column.dates.min} au ${column.dates.max}`)
  if (column.text) {
    const { min_length, max_length, avg_length } = column.text
    details.push(
      avg_length === null || avg_length === undefined
        ? `longueur ${min_length} à ${max_length}`
        : `longueur moyenne ${formatNumber(avg_length)}`,
    )
  }
  if (column.top_values?.length) {
    details.push(
      'fréquents : ' +
        column.top_values
          .slice(0, 3)
          .map((entry) => `${entry.value} (${formatCount(entry.count)})`)
          .join(', '),
    )
  }
  if (column.error_cells) details.push(`${formatCount(column.error_cells)} cellule(s) en erreur`)
  return details
}

export function cellText(value: unknown): string {
  if (value === null || value === undefined) return ''
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

// What to tell about a sheet besides its columns.
export function sheetNotes(sheet: TabularSheet): string[] {
  const notes = [...sheet.warnings]
  if (sheet.truncated) {
    notes.push(`Feuille tronquée : seules ses ${formatCount(sheet.rows)} premières lignes sont décrites et interrogeables.`)
  }
  if (!sheet.header_detected && sheet.columns.length) {
    notes.push('Aucun en-tête reconnu : les colonnes s’appellent col_1, col_2…')
  }
  return notes
}

// The SQL type DuckDB gives a column, back to the kind the analysis uses.
export function kindOfSqlType(sqlType: string): string {
  const type = sqlType.toUpperCase()
  if (type === 'BOOLEAN') return 'boolean'
  if (type.startsWith('TIMESTAMP')) return 'datetime'
  if (type.startsWith('DATE')) return 'date'
  if (type.startsWith('TIME')) return 'time'
  if (/^(TINYINT|SMALLINT|INTEGER|BIGINT|HUGEINT|INT)/.test(type)) return 'integer'
  if (/^(FLOAT|DOUBLE|DECIMAL|REAL)/.test(type)) return 'number'
  return 'text'
}

function legacyColumn(column: LegacyColumn, rows: number, index: number): TabularColumn {
  return {
    index,
    name: column.name,
    type: kindOfSqlType(column.type),
    non_null: rows - column.null_count,
    null: column.null_count,
    distinct: column.distinct_count,
    distinct_exact: true,
    sample_values: [],
    ...(column.numeric_stats
      ? {
          numeric: {
            count: rows - column.null_count,
            min: column.numeric_stats.min,
            max: column.numeric_stats.max,
            sum: null,
            mean: column.numeric_stats.mean,
            std: null,
            median: column.numeric_stats.median,
          },
        }
      : {}),
    ...(column.date_stats && column.date_stats.min && column.date_stats.max
      ? { dates: { min: column.date_stats.min, max: column.date_stats.max } }
      : {}),
    ...(column.text_stats ? { text: column.text_stats } : {}),
    ...(column.top_values?.length
      ? { top_values: column.top_values.map((entry) => ({ value: String(entry.value), count: entry.count })) }
      : {}),
  }
}

// The sheets to show: the file's own - or, for a profile from before they were kept, its one sheet (the profile of
// the document) dressed as one, so that the screen does not go empty until the document is indexed again.
export function sheetsOf(profile: TabularProfile): TabularSheet[] {
  if (profile.sheets.length) return profile.sheets
  const names = profile.columns.map((column) => column.name)
  return [
    {
      index: 0,
      name: 'Données',
      hidden: false,
      rows: profile.row_count,
      header_detected: true,
      truncated: false,
      columns: profile.columns.map((column, index) => legacyColumn(column, profile.row_count, index)),
      preview: profile.sample_rows.map((row) => names.map((name) => row[name])),
      warnings: [],
      table: null,
    },
  ]
}

export const isLegacyProfile = (profile: TabularProfile): boolean => profile.sheets.length === 0
