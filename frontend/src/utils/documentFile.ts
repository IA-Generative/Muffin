// The file a document was made from: where to download it, and how to open it on a page.

export interface FileLinkOptions {
  // Opened in the browser's own tab (a PDF, an image) rather than downloaded: only types that are safe to show are,
  // the backend downloads any other whatever is asked.
  inline?: boolean
  // The page a PDF opens on.
  page?: number
}

export function documentFileUrl(
  apiBase: string,
  collectionId: string,
  documentId: string,
  options: FileLinkOptions = {},
): string {
  const url = `${apiBase}/api/collections/${collectionId}/documents/${documentId}/file${options.inline ? '?inline=true' : ''}`
  return options.page && options.page > 0 ? `${url}#page=${options.page}` : url
}

// A web page (a document made from a URL) has no file: its name is its address.
export function hasFile(documentName: string): boolean {
  return !/^https?:\/\//i.test(documentName.trim())
}

// Only a PDF can be opened at a page by the browser.
export function opensAtPage(documentName: string): boolean {
  return /\.pdf$/i.test(documentName.trim())
}

// A page number typed by the reader, kept inside the document: undefined when it is not a number of its pages.
export function pageWithin(value: string | number, total: number): number | undefined {
  const page = typeof value === 'number' ? value : Number.parseInt(value.trim(), 10)
  return Number.isInteger(page) && page >= 1 && page <= total ? page : undefined
}
