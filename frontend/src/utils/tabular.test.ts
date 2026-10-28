import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { TabularColumn, TabularProfile, TabularSheet } from '../types/tabular.ts'
import {
  cellText,
  columnDetails,
  formatDistinct,
  formatNumber,
  isLegacyProfile,
  kindOfSqlType,
  sheetNotes,
  sheetsOf,
  typeLabel,
} from './tabular.ts'

// Intl groups thousands with a narrow no-break space: compare on plain spaces.
const plain = (text: string) => text.replace(/[  ]/g, ' ')

const column = (changes: Partial<TabularColumn> = {}): TabularColumn => ({
  index: 0,
  name: 'montant',
  type: 'number',
  non_null: 10,
  null: 0,
  distinct: 10,
  distinct_exact: true,
  sample_values: [],
  ...changes,
})

const sheet = (changes: Partial<TabularSheet> = {}): TabularSheet => ({
  index: 0,
  name: 'Ventes',
  hidden: false,
  rows: 10,
  header_detected: true,
  truncated: false,
  columns: [column()],
  preview: [],
  warnings: [],
  table: null,
  ...changes,
})

test('the types are named in French and an unknown one is left as it is', () => {
  assert.equal(typeLabel('integer'), 'entier')
  assert.equal(typeLabel('datetime'), 'date et heure')
  assert.equal(typeLabel('mixed'), 'mixte')
  assert.equal(typeLabel('geometry'), 'geometry')
})

test('numbers are written the French way and a missing one is a dash', () => {
  assert.equal(plain(formatNumber(1234567.891)), '1 234 567,89')
  assert.equal(formatNumber(null), '—')
  assert.equal(formatNumber(undefined), '—')
  assert.equal(formatNumber(0), '0')
})

test('a count the analysis stopped at is a lower bound and says so', () => {
  assert.equal(plain(formatDistinct({ distinct: 42, distinct_exact: true })), '42')
  assert.equal(plain(formatDistinct({ distinct: 1000, distinct_exact: false })), '≥ 1 000')
})

test('a numeric column is described by its range and its centre', () => {
  const details = columnDetails(
    column({ numeric: { count: 10, min: 1, max: 99.5, sum: 500, mean: 50, std: 3, median: 48 } }),
  ).map(plain)
  assert.deepEqual(details, ['min 1 · max 99,5', 'moyenne 50 · médiane 48'])
})

test('a text column is described by its length and its most frequent values', () => {
  const details = columnDetails(
    column({
      type: 'text',
      text: { min_length: 1, max_length: 20, avg_length: 6.5 },
      top_values: [
        { value: 'Nord', count: 12 },
        { value: 'Sud', count: 8 },
        { value: 'Est', count: 3 },
        { value: 'Ouest', count: 1 },
      ],
    }),
  ).map(plain)
  assert.deepEqual(details, ['longueur moyenne 6,5', 'fréquents : Nord (12), Sud (8), Est (3)'])
})

test('a date column gives its range, and error cells are counted', () => {
  const details = columnDetails(
    column({ type: 'date', dates: { min: '2026-01-01', max: '2026-12-31' }, error_cells: 2 }),
  ).map(plain)
  assert.deepEqual(details, ['du 2026-01-01 au 2026-12-31', '2 cellule(s) en erreur'])
})

test('a column with nothing to say has no details', () => {
  assert.deepEqual(columnDetails(column({ type: 'empty' })), [])
})

test('a cell is its text; an empty one is nothing and a nested one is its JSON', () => {
  assert.equal(cellText(null), '')
  assert.equal(cellText(undefined), '')
  assert.equal(cellText(0), '0')
  assert.equal(cellText(false), 'false')
  assert.equal(cellText('Nord'), 'Nord')
  assert.equal(cellText({ k: 1 }), '{"k":1}')
})

test('a sheet that was cut says how much of it is described', () => {
  const notes = sheetNotes(sheet({ truncated: true, rows: 1000000 })).map(plain)
  assert.equal(notes.length, 1)
  assert.match(notes[0]!, /tronquée.*1 000 000 premières lignes/)
})

test('a sheet without a header says its columns were named for it, and keeps the analysis warnings', () => {
  const notes = sheetNotes(sheet({ header_detected: false, warnings: ['Only the first 500 columns were analyzed'] }))
  assert.equal(notes[0], 'Only the first 500 columns were analyzed')
  assert.match(notes[1]!, /col_1/)
})

test('a sheet with a header and nothing to report has no notes', () => {
  assert.deepEqual(sheetNotes(sheet()), [])
})

test('an empty sheet is not told it has no header', () => {
  assert.deepEqual(sheetNotes(sheet({ header_detected: false, columns: [] })), [])
})

test('the SQL types are brought back to the kinds the analysis uses', () => {
  assert.deepEqual(
    ['BIGINT', 'INTEGER', 'DOUBLE', 'DECIMAL(10,2)', 'VARCHAR', 'BOOLEAN', 'DATE', 'TIMESTAMP', 'TIME'].map(kindOfSqlType),
    ['integer', 'integer', 'number', 'number', 'text', 'boolean', 'date', 'datetime', 'time'],
  )
})

const profile = (changes: Partial<TabularProfile> = {}): TabularProfile => ({
  row_count: 3,
  column_count: 2,
  format: 'csv',
  columns: [
    {
      name: 'region',
      type: 'VARCHAR',
      semantic_type: 'dimension',
      null_count: 0,
      distinct_count: 2,
      top_values: [{ value: 'Nord', count: 2 }],
    },
    {
      name: 'montant',
      type: 'BIGINT',
      semantic_type: 'measure',
      null_count: 1,
      distinct_count: 2,
      numeric_stats: { min: 10, max: 30, mean: 20, median: 20 },
    },
  ],
  sample_rows: [
    { region: 'Nord', montant: 10 },
    { region: 'Sud', montant: 30 },
  ],
  measures: ['montant'],
  dimensions: ['region'],
  text_columns: [],
  analysis_version: null,
  sheets: [],
  ...changes,
})

test('the sheets of a profile are its own', () => {
  const sheets = [sheet({ name: 'Ventes' }), sheet({ index: 1, name: 'Clients' })]
  assert.deepEqual(
    sheetsOf(profile({ sheets, analysis_version: 1 })).map((s) => s.name),
    ['Ventes', 'Clients'],
  )
  assert.equal(isLegacyProfile(profile({ sheets, analysis_version: 1 })), false)
})

test('a profile from before the sheets shows its one sheet instead of nothing', () => {
  const legacy = profile()
  assert.equal(isLegacyProfile(legacy), true)

  const [only] = sheetsOf(legacy)
  assert.ok(only)
  assert.equal(only.rows, 3)
  assert.deepEqual(
    only.columns.map((c) => [c.name, c.type, c.non_null, c.null]),
    [
      ['region', 'text', 3, 0],
      ['montant', 'integer', 2, 1],
    ],
  )
  assert.equal(only.columns[1]!.numeric?.max, 30)
  assert.deepEqual(only.columns[0]!.top_values, [{ value: 'Nord', count: 2 }])
  assert.deepEqual(only.preview, [
    ['Nord', 10],
    ['Sud', 30],
  ])
})

test('a legacy column without statistics has none to show', () => {
  const [only] = sheetsOf(
    profile({ columns: [{ name: 'a', type: 'VARCHAR', semantic_type: 'other', null_count: 0, distinct_count: 1 }] }),
  )
  assert.deepEqual(columnDetails(only!.columns[0]!), [])
})
