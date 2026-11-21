export const FLAG_LABELS = {
  bundle: 'Several documents in one file',
  'duplicate-pages': 'Contains duplicate pages',
  'duplicate-file': 'Identical copy of another file',
  'rotated-pages': 'Rotated pages',
  'low-ocr-confidence': 'Hard to read (low OCR confidence)',
  'not-in-workbook': 'Not listed in workbook',
  'no-declared-type': 'No type in workbook',
  'type-differs': 'Type differs from workbook',
  'pii:passport': 'Passport details',
  'pii:national-insurance': 'National Insurance number',
  'pii:date-of-birth': 'Date of birth',
  'sensitive:medical': 'Medical information',
}

export const flagLabel = (flag) => FLAG_LABELS[flag] || flag

export function Flags({ flags }) {
  if (!flags?.length) return null
  return (
    <span className="flags">
      {flags.map((f) => (
        <span key={f} className={`flag ${f.startsWith('pii') || f.startsWith('sensitive') ? 'flag-pii' : ''}`}>
          {flagLabel(f)}
        </span>
      ))}
    </span>
  )
}
