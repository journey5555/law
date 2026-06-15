import { esc, stripHtml } from './format.js'

export function filterArticles(articles) {
  const seen = new Set()
  return articles.filter(art => {
    if (art['조문여부'] && art['조문여부'] !== '조문') return false
    const key = art['조문키'] || `${art['조문번호']}_${art['조문시행일자']}`
    if (seen.has(key)) return false
    seen.add(key)
    const hasContent = (Array.isArray(art['항']) && art['항'].length > 0)
      || String(art['조문내용'] || '').trim().length > 0
    return hasContent
  })
}

export function buildArticleHtml(art) {
  const num   = art['조문번호'] || ''
  const title = art['조문제목'] || ''
  const hangs = Array.isArray(art['항']) ? art['항'] : []

  let body = ''
  if (hangs.length > 0) {
    body = hangs.map(hang => {
      const hangContent = String(hang['항내용'] || '').trim()
      const hos = Array.isArray(hang['호']) ? hang['호'] : []
      const hoHtml = hos.map(ho =>
        `<div class="ho-item">${esc(String(ho['호내용'] || '').trim())}</div>`
      ).join('')
      return `<div class="hang-item">${esc(hangContent)}${hoHtml}</div>`
    }).join('')
  } else {
    let content = String(art['조문내용'] || '').trim()
    const headerPattern = new RegExp(`^제${num}조(?:\\([^)]+\\))?\\s*`)
    content = content.replace(headerPattern, '').trim()
    if (content) body = `<div class="hang-item">${esc(content)}</div>`
  }

  return `<div class="article">
    <div class="article-header">제${esc(num)}조${title ? `(${esc(title)})` : ''}</div>
    ${body}
  </div>`
}

export function extractCitations(refArticles) {
  const text = stripHtml(refArticles)
  const results = []
  const seen = new Set()
  let currentLaw = ''

  const re = /((?:[가-힣]+\s)*[가-힣]+(?:법|령|규칙|예규|조례|지침))\s*제(\d+)조(?:의(\d+))?|제(\d+)조(?:의(\d+))?/g

  for (const m of text.matchAll(re)) {
    let joNum, joSub
    if (m[1]) {
      currentLaw = m[1].trim()
      joNum = parseInt(m[2])
      joSub = m[3] ? parseInt(m[3]) : 0
    } else {
      if (!currentLaw) continue
      joNum = parseInt(m[4])
      joSub = m[5] ? parseInt(m[5]) : 0
    }
    if (!joNum) continue
    const joText = `제${joNum}조${joSub ? `의${joSub}` : ''}`
    const key = `${currentLaw}|${joNum}|${joSub}`
    if (seen.has(key)) continue
    seen.add(key)
    results.push({ lawName: currentLaw, joText, joNum, joSub })
  }
  return results
}
